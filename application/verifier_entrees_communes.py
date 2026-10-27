"""Grandeurs communales et années invalides : aucune conclusion inventée."""
import json
import unittest

import champ_communal
import controles
import rapport_controles
import rapport_nl


INVALIDES = (False, True, -1., '1000', '', [], {}, float('nan'), float('inf'), -float('inf'), 10**400)


def resultat(dossier, identifiant):
    return next(r for r in controles.executer_tous(dossier) if r['id'] == identifiant)


class EntreesCommunes(unittest.TestCase):
    def bloque(self, controle):
        self.assertEqual(controle['statut'], 'bloque', controle)
        json.dumps(controle, allow_nan=False)

    def rapport(self, dossier):
        r = rapport_controles.composer(dossier)
        json.dumps(r, allow_nan=False)
        self.assertTrue(rapport_controles.en_texte(r))
        self.assertTrue(rapport_controles.en_html(r))
        self.assertTrue(rapport_nl.en_html(r))
        return r

    def test_seuils_refusent_capacite_et_puissance_invalides(self):
        for champ in ('capacite_kwh', 'puissance_kw'):
            for valeur in INVALIDES:
                with self.subTest(champ=champ, valeur=repr(valeur)):
                    dossier = {'capacite_kwh': 0., 'puissance_kw': 0., champ: valeur}
                    self.bloque(resultat(dossier, 'CTRL-SEUIL-PERMIS'))
                    self.bloque(controles.seuil_permis(dossier))
                    self.rapport(dossier)

    def test_champ_communal_ne_se_deduit_pas_d_une_capacite_invalide(self):
        for valeur in INVALIDES:
            with self.subTest(valeur=repr(valeur)):
                dossier = {'commune': 'Dordrecht', 'chimie_batterie': 'lithium',
                           'capacite_kwh': valeur, 'date_mise_en_service': None,
                           'bruit_facade_db': {'jour': 30., 'soir': 30., 'nuit': 30.},
                           'terrain_industriel_zone': False}
                champ = champ_communal.dans_le_champ(dossier, 'Dordrecht')
                self.assertEqual(champ['statut'], 'indetermine')
                self.assertIn('capacite_kwh', [m['champ'] for m in champ['manque']])
                controle = resultat(dossier, 'CTRL-BRUIT-COMMUNE')
                self.bloque(controle)
                self.assertNotIn('valeurs', controle)
                self.rapport(dossier)

    def test_capacite_valide_conserve_le_champ_preexistant(self):
        for capacite, statut in ((0., 'hors_champ'), (999., 'hors_champ'), (1000., 'dans_le_champ')):
            r = champ_communal.dans_le_champ({'chimie_batterie': 'lithium', 'capacite_kwh': capacite,
                                             'date_mise_en_service': None}, 'Dordrecht')
            self.assertEqual(r['statut'], statut)
        self.assertEqual(controles.seuil_permis({'capacite_kwh': 0., 'puissance_kw': 0.})['statut'], 'constat')

    def test_hauteur_invalide_ne_peut_etre_declaree_conforme(self):
        for valeur in INVALIDES:
            with self.subTest(valeur=repr(valeur)):
                dossier = {'commune': 'Hollands Kroon', 'soumis_a_permis': True,
                           'regime_lieu': 'bedrijfsmatig', 'hauteur_installation_m': valeur}
                self.bloque(resultat(dossier, 'CTRL-HAUTEUR-COMMUNE'))
                self.bloque(controles.hauteur_commune(dossier))
                self.rapport(dossier)

    def test_adjacence_texte_n_ouvre_pas_le_plafond_majore(self):
        for valeur in ('false', 'true', 0, 1, [], {}, float('nan')):
            dossier = {'commune': 'Hollands Kroon', 'soumis_a_permis': True,
                       'regime_lieu': 'bedrijfsmatig', 'hauteur_installation_m': 5.,
                       'adjacent_poste_380kv': valeur}
            controle = resultat(dossier, 'CTRL-HAUTEUR-COMMUNE')
            self.bloque(controle)
            self.assertEqual(controle['valeurs']['raison'], 'adjacence_380kv_invalide')
            self.assertNotIn('plafond_m', controle['valeurs'])
            self.assertIn('380 kV-station', rapport_nl._veld('adjacent_poste_380kv')[0])
        for valeur, statut in ((False, 'alerte'), (True, 'constat'), (None, 'alerte')):
            dossier['adjacent_poste_380kv'] = valeur
            self.assertEqual(resultat(dossier, 'CTRL-HAUTEUR-COMMUNE')['statut'], statut)

    def test_plafond_parc_refuse_les_puissances_invalides(self):
        for champ in ('puissance_kw', 'puissance_pointe_parc_pv_kw'):
            for valeur in INVALIDES:
                with self.subTest(champ=champ, valeur=repr(valeur)):
                    dossier = {'commune': 'Best', 'zone': 'buitengebied', 'couplee_parc_pv': True,
                               'puissance_kw': 100., 'puissance_pointe_parc_pv_kw': 200., champ: valeur}
                    self.bloque(resultat(dossier, 'CTRL-PLAFOND-PARC-PV'))
                    self.bloque(controles.plafond_parc_pv(dossier))
                    self.rapport(dossier)

    def test_annee_invalide_bloque_au_lieu_de_planter_ou_tronquer(self):
        valeurs = (False, True, 0, -1, 2027.5, '2027.5', 'inconnu', [], {}, float('nan'), float('inf'), 9996, 10**400)
        for valeur in valeurs:
            with self.subTest(valeur=repr(valeur)):
                dossier = {'statut_zone_afname': 'beschikbaar', 'statut_zone_teruglevering': 'beschikbaar',
                           'date_carte': '2026-09-27', 'annee_liberation_annoncee': valeur}
                controle = resultat(dossier, 'CTRL-ZONE')
                self.bloque(controle)
                self.assertEqual(controle['valeurs']['raison'], 'annee_liberation_invalide')
                self.assertNotIn('annee_annoncee', controle['valeurs'])
                self.rapport(dossier)

    def test_annee_entiere_et_absence_restent_possibles(self):
        for valeur, attendu in ((2027, 2027), (2027., 2027), ('2027', 2027), (9995, 9995), (None, None), ('', None)):
            dossier = {'statut_zone_afname': 'beschikbaar', 'statut_zone_teruglevering': 'beschikbaar',
                       'date_carte': '2026-09-27', 'annee_liberation_annoncee': valeur}
            controle = resultat(dossier, 'CTRL-ZONE')
            self.assertEqual(controle['statut'], 'constat')
            self.assertEqual(controle['valeurs'].get('annee_annoncee'), attendu)
            if attendu:
                self.assertEqual(controle['valeurs']['annee_a_tester'], attendu + 4)

    def test_presentation_de_la_demande_ne_convertit_pas_les_valeurs_invalides(self):
        for valeur in (False, -1., {}, 'abc', float('nan'), float('inf'), 10**400):
            dossier = {'capacite_kwh': valeur, 'puissance_kw': valeur}
            rapport = self.rapport(dossier)
            self.assertIn('puissance invalide', rapport['aangevraagd'])
            self.assertIn('capacité invalide', rapport['aangevraagd'])
        rapport = self.rapport({'capacite_kwh': 0., 'puissance_kw': 0.})
        self.assertEqual(rapport['aangevraagd'], '0 kW, 0 kWh')

    def test_une_entree_invalide_ne_bloque_pas_un_controle_independant(self):
        dossier = {'capacite_kwh': float('nan'), 'puissance_kw': 0., 'profil_kw': [10.], 'gtv_kw': 20.}
        self.bloque(resultat(dossier, 'CTRL-SEUIL-PERMIS'))
        self.assertEqual(resultat(dossier, 'CTRL-MARGE')['valeurs']['marge_kw'], 10.)


if __name__ == '__main__':
    unittest.main()
