"""Blocs contractuels NL : même instant, même décision, y compris aux transitions."""
import copy
import sys
import unittest
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from controles import transportrecht, executer_tous
from rapport_nl import _zin
from verifier_periode_exacte import periode


def dossier(fin='2026-08-01T08:15:00+02:00', blocs='08:00-09:00', puissance=100, limite=0):
    return {'type_transportrecht': 'tijdsblok', 'blocs_transport': blocs,
            'profil_horodatages': [fin], 'profil_kw': [puissance], 'gtv_hors_bloc_kw': limite}


class BlocsHorodates(unittest.TestCase):
    def test_meme_instant_utc_et_local_meme_verdict(self):
        for dates in [('2026-08-01T08:15:00+02:00', '2026-08-01T06:15:00Z'),
                      ('2026-01-01T08:15:00+01:00', '2026-01-01T07:15:00Z')]:
            resultats = [transportrecht(dossier(fin)) for fin in dates]
            self.assertEqual(resultats[0], resultats[1])
            self.assertEqual(resultats[0]['statut'], 'constat')

    def test_hors_bloc_utc_meme_alerte_avec_trace_locale(self):
        local = transportrecht(dossier('2026-08-01T09:15:00+02:00'))
        utc = transportrecht(dossier('2026-08-01T07:15:00Z'))
        self.assertEqual(local, utc)
        self.assertEqual(utc['statut'], 'alerte')
        self.assertEqual(utc['valeurs']['premiers_depassements'], [
            {'debut_local': '2026-08-01T09:00:00+02:00', 'fin_locale': '2026-08-01T09:15:00+02:00', 'puissance_kw': 100}])

    def test_retour_hiver_quart_commence_0245_heure_ete(self):
        for fin in ['2026-10-25T02:00:00+01:00', '2026-10-25T01:00:00Z']:
            r = transportrecht(dossier(fin, '02:00-03:00'))
            self.assertEqual(r['statut'], 'constat', r)
            r = transportrecht(dossier(fin, '01:00-02:00'))
            self.assertEqual(r['statut'], 'alerte', r)
            self.assertEqual(r['valeurs']['premiers_depassements'][0]['debut_local'], '2026-10-25T02:45:00+02:00')

    def test_passage_ete_quart_commence_0145(self):
        r = transportrecht(dossier('2026-03-29T03:00:00+02:00', '01:00-02:00'))
        self.assertEqual(r['statut'], 'constat', r)
        r = transportrecht(dossier('2026-03-29T03:00:00+02:00', '02:00-03:00'))
        self.assertEqual(r['statut'], 'alerte', r)

    def test_jours_dst_nombre_heures_dans_bloc(self):
        for jour, total, hors in [('2026-03-29', 92, 92), ('2026-10-25', 100, 92)]:
            for utc in (False, True):
                dates = periode(jour, objets=True)
                if utc:
                    dates = [d.astimezone(timezone.utc) for d in dates]
                d = dossier(blocs='02:00-03:00') | {'profil_horodatages': dates, 'profil_kw': [100] * total}
                r = transportrecht(d)
                self.assertEqual(r['valeurs']['quarts_evalues'], total)
                self.assertEqual(r['valeurs']['quarts_hors_bloc_au_dessus'], hors)

    def test_debut_inclus_fin_exclue(self):
        for fin, statut in [('08:00', 'alerte'), ('08:15', 'constat'), ('09:00', 'constat'), ('09:15', 'alerte')]:
            r = transportrecht(dossier(f'2026-08-01T{fin}:00+02:00'))
            self.assertEqual(r['statut'], statut)

    def test_bloc_traversant_minuit(self):
        for fin, statut in [('22:15', 'constat'), ('00:15', 'constat'), ('06:00', 'constat'), ('06:15', 'alerte')]:
            self.assertEqual(transportrecht(dossier(f'2026-08-01T{fin}:00+02:00', '22:00-06:00'))['statut'], statut)

    def test_plusieurs_blocs_et_chevauchement_sans_double_compte(self):
        d = dossier('2026-08-01T09:15:00+02:00', '08:00-09:00,08:30-09:30,12:00-13:00')
        self.assertEqual(transportrecht(d)['statut'], 'constat')
        d['profil_horodatages'] = ['2026-08-01T10:00:00+02:00']
        self.assertEqual(transportrecht(d)['valeurs']['quarts_hors_bloc_au_dessus'], 1)

    def test_jour_complet_explicite(self):
        d = dossier(blocs='00:00-24:00') | {'profil_horodatages': periode(), 'profil_kw': [100] * 96}
        self.assertEqual(transportrecht(d)['statut'], 'constat')

    def test_heures_invalides_et_bornes_identiques_refusees(self):
        for blocs in ['00:00-24:59', '08:00-08:00', '00:00-00:00', '24:00-06:00',
                      '08:07-09:00', '08:00-09:01', '08:00-25:00', '08:00-09:60',
                      '8:0-9:0', 'nuit', '08:00-09:00,', '-1:00-09:00']:
            with self.subTest(blocs=blocs):
                self.assertEqual(transportrecht(dossier(blocs=blocs))['statut'], 'bloque')

    def test_bornes_au_quart_d_heure_acceptables(self):
        self.assertEqual(transportrecht(dossier(blocs='8:00-08:15'))['statut'], 'constat')

    def test_longueurs_differentes_refusees_sans_troncature(self):
        for horaires, puissances in [(['2026-08-01T08:15:00+02:00'], [100, 999]),
                                     (['2026-08-01T08:15:00+02:00', '2026-08-01T08:30:00+02:00'], [100])]:
            d = dossier() | {'profil_horodatages': horaires, 'profil_kw': puissances}
            self.assertEqual(transportrecht(d)['statut'], 'bloque')

    def test_dates_naives_decalees_et_invalides_refusees(self):
        for fin in ['2026-08-01T08:15:00', '2026-08-01T08:15:01+02:00', 'date', None, True]:
            with self.subTest(fin=fin):
                self.assertEqual(transportrecht(dossier(fin))['statut'], 'bloque')

    def test_horodatages_vides_refuses(self):
        for horaires, valeurs in [([], []), ([], [100]), (['2026-08-01T08:15:00+02:00'], [])]:
            r = transportrecht(dossier() | {'profil_horodatages': horaires, 'profil_kw': valeurs})
            self.assertEqual(r['statut'], 'bloque')

    def test_trou_doublon_inverse_refuses(self):
        for autre in ['2026-08-01T08:45:00+02:00', '2026-08-01T08:15:00+02:00', '2026-08-01T08:00:00+02:00']:
            d = dossier() | {'profil_horodatages': ['2026-08-01T08:15:00+02:00', autre], 'profil_kw': [100, 100]}
            self.assertEqual(transportrecht(d)['statut'], 'bloque')

    def test_non_finis_negatifs_et_booleens_refuses(self):
        for valeur in [float('nan'), float('inf'), -1, 10_000_001, True, None, {}, 'abc', 10**400]:
            for champ in ('limite', 'puissance'):
                with self.subTest(champ=champ, valeur=str(valeur)[:20]):
                    self.assertEqual(transportrecht(dossier(**{champ: valeur}))['statut'], 'bloque')

    def test_limite_absente_ne_devient_pas_zero(self):
        d = dossier(); del d['gtv_hors_bloc_kw']
        r = transportrecht(d)
        self.assertEqual(r['statut'], 'bloque')
        self.assertTrue(any(m['champ'] == 'gtv_hors_bloc_kw' for m in r['manque']))

    def test_egalite_limite_hors_bloc_pas_depassement(self):
        self.assertEqual(transportrecht(dossier('2026-08-01T10:15:00+02:00', limite=100))['statut'], 'constat')
        self.assertEqual(transportrecht(dossier('2026-08-01T10:15:00+02:00', limite=99.9))['statut'], 'alerte')

    def test_trace_limitee_a_cinq_et_compte_complet(self):
        d = dossier() | {'profil_horodatages': periode(), 'profil_kw': [100] * 96}
        r = transportrecht(d)
        self.assertEqual(r['valeurs']['quarts_hors_bloc_au_dessus'], 92)
        self.assertEqual(len(r['valeurs']['premiers_depassements']), 5)

    def test_entrees_inchangees(self):
        d = dossier(); avant = copy.deepcopy(d)
        transportrecht(d)
        self.assertEqual(d, avant)

    def test_erreur_traduite_en_neerlandais(self):
        for d in [dossier(blocs='08:00-08:00'), dossier(limite=float('nan'))]:
            message, _ = _zin(transportrecht(d))
            self.assertNotIn('puissance', message)
            self.assertIn('tijdsblokken', message)

    def test_rapport_declare_fuseau(self):
        message, _ = _zin(transportrecht(dossier()))
        self.assertIn('Europe/Amsterdam', message)

    def test_regimes_autres_que_blocs_non_modifies(self):
        self.assertEqual(transportrecht({'type_transportrecht': 'vast'})['statut'], 'constat')
        self.assertEqual(transportrecht({'type_transportrecht': 'non_firm'})['statut'], 'alerte')

    def test_dates_extremes_bloquent_sans_exception(self):
        for fin in ['0001-01-01T00:00:00Z', '9999-12-31T23:45:00Z']:
            self.assertEqual(transportrecht(dossier(fin))['statut'], 'bloque')

    def test_mauvaise_periode_ne_peut_pas_etre_contournee_par_un_profil_kw_separe(self):
        d = dossier(blocs='00:00-24:00') | {'profil_horodatages': periode()[:-4],
             'profil_brut': [100] * 92, 'profil_kw': [100] * 92, 'unite_profil': 'kw',
             'kwmax_facture': 100, 'periode_facture_debut': '2026-09-01', 'periode_facture_fin': '2026-09-01'}
        r = next(r for r in executer_tous(d) if r['id'] == 'CTRL-TRANSPORTRECHT')
        self.assertEqual(r['statut'], 'bloque')
        d['type_transportrecht'] = 'vast'
        r = next(r for r in executer_tous(d) if r['id'] == 'CTRL-TRANSPORTRECHT')
        self.assertEqual(r['statut'], 'constat')

    def test_unite_incoherente_bloque_aussi_les_blocs(self):
        d = dossier(blocs='00:00-24:00') | {'profil_horodatages': periode(),
             'profil_brut': [25] * 96, 'profil_kw': [25] * 96, 'unite_profil': 'kw',
             'kwmax_facture': 100, 'periode_facture_debut': '2026-09-01', 'periode_facture_fin': '2026-09-01'}
        r = next(r for r in executer_tous(d) if r['id'] == 'CTRL-TRANSPORTRECHT')
        self.assertEqual(r['statut'], 'bloque')
        d['unite_profil'] = 'kwh_par_quart'
        r = next(r for r in executer_tous(d) if r['id'] == 'CTRL-TRANSPORTRECHT')
        self.assertEqual(r['statut'], 'constat')


if __name__ == '__main__':
    unittest.main()
