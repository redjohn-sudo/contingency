"""Divergence ATO/facture, preuve humaine déclarée et propagation de la référence."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

import controles
import diagnostic
import extraction_fiche
import modele_dossier
import rapport_controles
import rapport_nl
import reference_gtv
import verifier_coherence_entrees as exemples
import verifier_diagnostic as exemples_diagnostic


def confirmation(valeur=6500.):
    return {'valeur_kw': valeur, 'confirme_actuel': True,
            'source_document': 'Factuur september 2026, pagina 1',
            'date_document': '2026-09-24', 'verifie_par': 'Lecteur de test',
            'date_verification': '2026-09-27'}


def dossier(confirme=False):
    d = exemples.dossier()
    d.update(profil_brut=[7000.] * 96, kwmax_facture=7000., kwh_facture=168000.,
             gtv_kw=15000., gtv_declare_kw=6500., tarif_kw_mois_eur=2., mois_factures=12)
    if confirme:
        d['confirmation_gtv_declare'] = confirmation()
    return d


class ReferenceGtv(unittest.TestCase):
    def resultats(self, d):
        return {r['id']: r for r in controles.executer_tous(d)}

    def test_divergence_sans_confirmation_ne_fabrique_pas_de_marge(self):
        resultats = self.resultats(dossier())
        for ident in ('CTRL-MARGE', 'CTRL-DEPASSEMENT', 'CTRL-GTV-DECLARE', 'CTRL-CAPACITE-DORMANTE', 'CTRL-CM-1MW'):
            r = resultats[ident]
            self.assertEqual(r['statut'], 'bloque', ident)
            self.assertEqual(r['valeurs']['raison'], 'gtv_reference_non_confirmee')
            self.assertNotIn('marge_kw', r['valeurs'])
            self.assertNotIn('gtv_opposable_kw', r['valeurs'])
            self.assertNotIn('cout_eur', r['valeurs'])
        self.assertEqual(resultats['COH-UNITE']['statut'], 'constat')

    def test_derniere_declaration_confirmee_est_la_reference(self):
        resultats = self.resultats(dossier(True))
        marge = resultats['CTRL-MARGE']
        self.assertEqual(marge['statut'], 'alerte')
        self.assertEqual(marge['valeurs']['marge_kw'], -500.)
        self.assertEqual(marge['valeurs']['gtv_kw'], 6500.)
        self.assertEqual(marge['valeurs']['nombre_quarts_en_depassement'], 96)
        self.assertEqual(resultats['CTRL-DEPASSEMENT']['valeurs']['blocs_en_depassement'], [1])
        self.assertEqual(resultats['CTRL-GTV-DECLARE']['valeurs']['gtv_opposable_kw'], 6500.)
        self.assertEqual(marge['reference_gtv']['gtv_ato_kw'], 15000.)
        self.assertFalse(marge['reference_gtv']['piece_authentifiee_par_application'])
        self.assertIn('RES-012', marge['contraintes'])

    def test_cout_historique_non_deduit_de_la_seule_reference_actuelle(self):
        cout = self.resultats(dossier(True))['CTRL-CAPACITE-DORMANTE']
        self.assertEqual(cout['statut'], 'bloque')
        self.assertEqual(cout['valeurs']['raison'], 'gtv_cout_periode_non_confirmee')
        self.assertNotIn('cout_eur', cout['valeurs'])
        self.assertIn('gefactureerde maanden', rapport_nl._zin(cout)[0])

    def test_confirmation_manquante_ou_mal_formee(self):
        for valeur in (None, False, True, 'oui', [], {}):
            d = dossier(); d['confirmation_gtv_declare'] = valeur
            self.assertEqual(reference_gtv.etablir(d)['statut'], 'bloque')
        champs = {
            'confirme_actuel': (False, 1, 'true', None),
            'valeur_kw': (6400, False, '6500', float('nan'), float('inf')),
            'source_document': ('', ' ', False, []),
            'verifie_par': ('', ' ', False, []),
            'date_document': ('20260924', '2026-09-31', '2026-09-28', False, None),
            'date_verification': ('20260927', '2026-09-23', '2026-09-28', False, None),
        }
        for champ, valeurs in champs.items():
            for valeur in valeurs:
                with self.subTest(champ=champ, valeur=repr(valeur)):
                    d = dossier(True); d['confirmation_gtv_declare'][champ] = valeur
                    r = reference_gtv.etablir(d, aujourd_hui=date(2026, 9, 27))
                    self.assertEqual(r['statut'], 'bloque')
                    json.dumps(r, allow_nan=False)

    def test_changement_de_valeur_invalide_ancienne_confirmation(self):
        d = dossier(True); d['gtv_declare_kw'] = 6400.
        self.assertEqual(self.resultats(d)['CTRL-MARGE']['statut'], 'bloque')

    def test_reference_nulle_confirmee_ne_revient_pas_a_ato(self):
        d = dossier(True); d.update(gtv_declare_kw=0., confirmation_gtv_declare=confirmation(0.))
        r = self.resultats(d)['CTRL-MARGE']
        self.assertEqual(r['valeurs']['gtv_kw'], 0.)
        self.assertEqual(r['valeurs']['marge_kw'], -7000.)
        self.assertIsNone(r['valeurs']['taux_utilisation'])
        rapport_nl.en_html(rapport_controles.composer(d))

    def test_reference_nulle_non_confirmee_bloque(self):
        d = dossier(); d['gtv_declare_kw'] = 0.
        self.assertEqual(self.resultats(d)['CTRL-MARGE']['statut'], 'bloque')

    def test_declaration_invalide_bloque_aussi_la_marge_ato(self):
        for valeur in (False, -1, '6500', float('nan'), float('inf')):
            d = dossier(); d['gtv_declare_kw'] = valeur
            self.assertEqual(self.resultats(d)['CTRL-MARGE']['statut'], 'bloque')
            r = rapport_controles.composer(d)
            json.dumps(r, allow_nan=False)
            rapport_nl.en_html(r)

    def test_absence_ou_egalite_ne_change_pas_la_reference_saisie(self):
        for valeur in (None, 15000.):
            d = dossier(); d['gtv_declare_kw'] = valeur
            self.assertIsNone(reference_gtv.etablir(d))
            self.assertEqual(self.resultats(d)['CTRL-MARGE']['valeurs']['gtv_kw'], 15000.)

    def test_hausse_non_confirmee_ne_devient_pas_un_droit(self):
        d = dossier(); d['gtv_declare_kw'] = 20000.
        self.assertEqual(self.resultats(d)['CTRL-MARGE']['statut'], 'bloque')

    def test_dossier_et_confirmation_non_modifies(self):
        d = dossier(True); original = deepcopy(d)
        self.resultats(d)
        self.assertEqual(d, original)

    def test_pertes_et_reference_gtv_sont_appliquees_ensemble(self):
        d = dossier(True)
        d.update(kwmax_facture=7098., kwh_facture=168000. * 1.014, mesure_au_point_de_livraison=False)
        marge = self.resultats(d)['CTRL-MARGE']
        self.assertAlmostEqual(marge['valeurs']['pointe_kw'], 7098.)
        self.assertAlmostEqual(marge['valeurs']['marge_kw'], -598.)

    def test_rapports_fr_nl_avec_et_sans_confirmation(self):
        for confirme in (False, True):
            r = rapport_controles.composer(dossier(confirme))
            json.dumps(r, allow_nan=False)
            fr, nl = rapport_controles.en_texte(r), rapport_nl.en_html(r)
            if confirme:
                self.assertIn('dernière déclaration 6500.0 kW', fr)
                self.assertIn('laatst opgegeven vermogen 6.500,0 kW', nl)
                self.assertIn('Lecteur de test', nl)
                self.assertIn('niet de authenticiteit', nl)
            else:
                self.assertIn('puissance actuelle reste à confirmer', fr)
                self.assertNotIn('Ruimte binnen het huidige contract:', nl)
                self.assertIn('Actueel transportvermogen nog te bevestigen', nl)

    def test_source_et_nom_echappes_dans_les_html(self):
        d = dossier(True)
        d['confirmation_gtv_declare'].update(source_document='<script>alerte()</script>', verifie_par='<b>lecteur</b>')
        r = rapport_controles.composer(d)
        for rendu in (rapport_controles.en_html(r), rapport_nl.en_html(r)):
            self.assertIn('&lt;script&gt;', rendu)
            self.assertNotIn('<script>alerte()', rendu)

    def test_modele_vierge_et_ia_ne_preconfirment_pas(self):
        self.assertIsNone(diagnostic.modele()['valeurs']['confirmation_gtv_declare']['valeur'])
        self.assertIsNone(modele_dossier.normaliser({'suivi': {}})['confirmation_gtv_declare'])
        self.assertNotIn('confirmation_gtv_declare', extraction_fiche.CHAMPS)

    def test_chaine_diagnostic_avec_confirmation_documentee(self):
        with tempfile.TemporaryDirectory() as rep:
            fiche = exemples_diagnostic._fiche(Path(rep), 'kwh_par_quart')
            fiche['valeurs']['gtv_kw']['valeur'] = 500.
            fiche['valeurs']['gtv_declare_kw']['valeur'] = 350.
            fiche['valeurs']['confirmation_gtv_declare']['valeur'] = confirmation(350.)
            resultat = diagnostic.produire(fiche, Path(rep) / 'sortie')
            self.assertIn('dernière déclaration 350.0 kW', resultat.with_suffix('.txt').read_text())
            nl = resultat.with_name('rapport-nl.html').read_text()
            self.assertIn('laatst opgegeven vermogen 350,0 kW', nl)
            self.assertIn('-50,0 kW', nl)


if __name__ == '__main__':
    unittest.main()
