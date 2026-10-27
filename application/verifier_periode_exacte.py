"""Périodes synthétiques, bornes civiles NL et CSV sans ambiguïté de temps."""
import sys
import base64
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coherence_mesures as cm
import serveur
import controles
import rapport_controles
import rapport_nl
from horodatages import lire_fin_quart

AMSTERDAM = ZoneInfo('Europe/Amsterdam')


def periode(debut='2026-09-01', fin=None, zone=AMSTERDAM, objets=False):
    fin = fin or debut
    borne = datetime.combine(date.fromisoformat(debut), time.min, zone).astimezone(timezone.utc)
    terme = datetime.combine(date.fromisoformat(fin) + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    dates = [(borne + timedelta(minutes=15 * (i + 1))).astimezone(zone)
             for i in range(int((terme - borne).total_seconds() / 900))]
    return dates if objets else [d.isoformat() for d in dates]


def texte(dates=None, valeur='12.5'):
    return 'fin_intervalle,puissance_kw\n' + '\n'.join(f'{d},{valeur}' for d in (dates or periode()))


class PeriodeExacte(unittest.TestCase):
    def controle(self, dates, debut='2026-09-01', fin=None, nombre=None, **options):
        return cm.controler_periode(dates, (debut, fin or debut), len(dates) if nombre is None else nombre, **options)

    def test_jour_normal_96_quarts(self):
        r = self.controle(periode())
        self.assertEqual(r['statut'], 'constat')
        self.assertEqual(r['valeurs']['attendues'], 96)
        self.assertEqual(r['valeurs']['fuseau_facture'], 'Europe/Amsterdam')

    def test_refuse_un_a_quatre_quarts_manquants(self):
        for n in range(1, 5):
            for dates in (periode()[n:], periode()[:-n]):
                with self.subTest(n=n, debut=dates[0]):
                    self.assertEqual(self.controle(dates)['statut'], 'bloque')

    def test_refuse_compte_de_mesures_different_des_dates(self):
        for nombre in (95, 97, 96.0, '96', True):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.controle(periode(), nombre=nombre)['statut'], 'bloque')
        self.assertEqual(self.controle(periode()[:-4], nombre=96)['statut'], 'bloque')

    def test_refuse_doublon_masquant_un_trou(self):
        dates = periode()
        dates[40] = dates[39]
        self.assertEqual(self.controle(dates)['statut'], 'bloque')

    def test_refuse_trou_et_ordre_inverse(self):
        for dates in (periode()[:40] + periode()[41:], list(reversed(periode()))):
            self.assertEqual(self.controle(dates)['statut'], 'bloque')

    def test_refuse_bornes_decalees_avec_bon_compte(self):
        for minutes in (-15, 15, 60):
            dates = [(d + timedelta(minutes=minutes)).isoformat() for d in periode(objets=True)]
            self.assertEqual(self.controle(dates)['statut'], 'bloque')

    def test_refuse_debut_de_quart_utilise_comme_fin(self):
        dates = [(d - timedelta(minutes=15)).isoformat() for d in periode(objets=True)]
        self.assertEqual(self.controle(dates)['valeurs']['hors_periode'], 1)

    def test_refuse_date_sans_fuseau(self):
        dates = [d.replace(tzinfo=None).isoformat() for d in periode(objets=True)]
        self.assertEqual(self.controle(dates)['valeurs']['raison'], 'horodatages_invalides')

    def test_refuse_quarts_de_cales_une_seconde(self):
        dates = [(d + timedelta(seconds=1)).isoformat() for d in periode(objets=True)]
        self.assertEqual(self.controle(dates)['statut'], 'bloque')

    def test_utc_et_heure_locale_designent_la_meme_periode(self):
        dates = [d.astimezone(timezone.utc).isoformat() for d in periode(objets=True)]
        self.assertEqual(self.controle(dates)['statut'], 'constat')
        self.assertEqual(self.controle(dates)['valeurs']['premier_quart_fin'], '2026-08-31T22:15:00+00:00')

    def test_mars_92_quarts_et_octobre_100(self):
        for jour, attendu in [('2026-03-29', 92), ('2026-10-25', 100)]:
            for objets in (True, False):
                with self.subTest(jour=jour, objets=objets):
                    r = self.controle(periode(jour, objets=objets), jour)
                    self.assertEqual(r['statut'], 'constat', r)
                    self.assertEqual(r['valeurs']['attendues'], attendu)

    def test_mois_entiers_avec_changement_heure(self):
        for debut, fin, n in [('2026-03-01', '2026-03-31', 2972), ('2026-10-01', '2026-10-31', 2980)]:
            r = self.controle(periode(debut, fin), debut, fin)
            self.assertEqual(r['statut'], 'constat', r)
            self.assertEqual(r['valeurs']['attendues'], n)

    def test_periode_non_calendaire_traversant_changement_heure(self):
        r = self.controle(periode('2026-03-15', '2026-04-14'), '2026-03-15', '2026-04-14')
        self.assertEqual(r['statut'], 'constat')
        self.assertEqual(r['valeurs']['attendues'], 2972)

    def test_fuseau_explicitement_utc_a_96_quarts(self):
        dates = periode('2026-03-29', zone=timezone.utc)
        self.assertEqual(self.controle(dates, '2026-03-29', fuseau='UTC')['statut'], 'constat')
        self.assertEqual(self.controle(dates, '2026-03-29')['statut'], 'bloque')

    def test_annee_bissextile_complete(self):
        r = self.controle(periode('2024-01-01', '2024-12-31'), '2024-01-01', '2024-12-31')
        self.assertEqual(r['statut'], 'constat')
        self.assertEqual(r['valeurs']['attendues'], 35136)

    def test_dates_facture_invalides_ne_levent_pas_exception(self):
        for bornes in [('erreur', '2026-09-01'), ('2026-09-02', '2026-09-01'),
                       ('2026-09-01garbage', '2026-09-01'), ('9999-12-31', '9999-12-31'),
                       ('2026-09-01',), '2026-09-01', 42]:
            with self.subTest(bornes=bornes):
                r = cm.controler_periode(periode(), bornes, 96)
                self.assertEqual(r['statut'], 'bloque')

    def test_fuseau_invalide_bloque(self):
        for zone in ['Absent/Fuseau', None, '/etc/passwd']:
            self.assertEqual(self.controle(periode(), fuseau=zone)['statut'], 'bloque')

    def test_donnees_absentes_bloquent(self):
        self.assertEqual(cm.controler_periode([], ('2026-09-01', '2026-09-01'), 0)['statut'], 'bloque')
        self.assertEqual(cm.controler_periode(periode(), None, 96)['statut'], 'bloque')

    def test_entrees_ne_sont_pas_modifiees(self):
        dates = periode()
        avant = list(dates)
        self.controle(dates)
        self.assertEqual(dates, avant)


class CsvCanoniqueStrict(unittest.TestCase):
    def test_valide_et_bom(self):
        for entete in ('', '\ufeff'):
            valeurs, dates = serveur._lire_profil_detaille(entete + texte())
            self.assertEqual(valeurs, [12.5] * 96)
            self.assertEqual(dates, periode())

    def test_colonnes_inversees_acceptables_si_uniques(self):
        contenu = 'puissance_kw,fin_intervalle\n' + '\n'.join(f'12.5,{d}' for d in periode())
        self.assertEqual(serveur._lire_profil_detaille(contenu)[0], [12.5] * 96)

    def test_colonne_dupliquee_refusee(self):
        contenu = 'fin_intervalle,puissance_kw,puissance_kw\n' + '\n'.join(f'{d},999,12.5' for d in periode())
        with self.assertRaisesRegex(ValueError, 'uniques'):
            serveur._lire_profil_detaille(contenu)

    def test_date_naive_refusee(self):
        with self.assertRaisesRegex(ValueError, 'fuseau'):
            serveur._lire_profil_detaille(texte([d[:-6] for d in periode()]))

    def test_melange_naif_date_refuse_par_valueerror(self):
        dates = periode(); dates[1] = dates[1][:-6]
        with self.assertRaises(ValueError):
            serveur._lire_profil_detaille(texte(dates))

    def test_secondes_et_fractions_refusees(self):
        for ecart in (timedelta(seconds=1), timedelta(microseconds=1), timedelta(minutes=1)):
            with self.assertRaisesRegex(ValueError, 'quart'):
                serveur._lire_profil_detaille(texte([(d + ecart).isoformat() for d in periode(objets=True)]))

    def test_champs_manquants_et_supplementaires_refuses(self):
        for mauvaise in ['2026-09-01T00:15:00+02:00', ',12.5', '2026-09-01T00:15:00+02:00,',
                         '2026-09-01T00:15:00+02:00,12.5,surplus', ' ,12.5']:
            lignes = texte().splitlines(); lignes[1] = mauvaise
            with self.subTest(ligne=mauvaise), self.assertRaises(ValueError):
                serveur._lire_profil_detaille('\n'.join(lignes))

    def test_champ_csv_non_ferme_refuse(self):
        with self.assertRaisesRegex(ValueError, 'mal formé'):
            serveur._lire_profil_detaille('fin_intervalle,puissance_kw\n"sans fermeture')

    def test_valeurs_incorrectes_refusees(self):
        for valeur in ['NaN', 'inf', '-inf', '-0.01', '10000001', 'abc', 'True']:
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                serveur._lire_profil_detaille(texte(valeur=valeur))

    def test_zero_et_borne_superieure_acceptes(self):
        for valeur in ['0', '10000000']:
            self.assertEqual(serveur._lire_profil_detaille(texte(valeur=valeur))[0], [float(valeur)] * 96)

    def test_heure_utc_z_preservee(self):
        dates = [d.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') for d in periode(objets=True)]
        self.assertEqual(serveur._lire_profil_detaille(texte(dates))[1][0], '2026-08-31T22:15:00+00:00')

    def test_jours_dst_acceptes_seulement_en_mode_civil(self):
        for jour, n in [('2026-03-29', 92), ('2026-10-25', 100)]:
            contenu = texte(periode(jour))
            self.assertEqual(len(serveur._lire_profil_detaille(contenu, jours_civils=True)[0]), n)
            with self.assertRaises(ValueError):
                serveur._lire_profil_detaille(contenu)

    def test_longueur_et_type_entree(self):
        for contenu in [None, {}, '', texte(periode()[:10])]:
            with self.subTest(contenu=str(contenu)[:20]), self.assertRaises(ValueError):
                serveur._lire_profil_detaille(contenu)

    def test_doublon_trou_et_ordre_refuses(self):
        dates = periode(); dates[1] = dates[0]
        for contenu in [texte(dates), texte(list(reversed(periode())))]:
            with self.assertRaises(ValueError):
                serveur._lire_profil_detaille(contenu)

    def test_erreur_date_hors_plage_uniforme(self):
        for valeur in ['0001-01-01T00:00:00+14:00', '9999-12-31T23:45:00-14:00', None, 12, 'pas une date']:
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                lire_fin_quart(valeur)


class ChainePeriode(unittest.TestCase):
    def test_http_refuse_dates_sans_fuseau_et_csv_tronque_sans_creer_dossier(self):
        documents = [{'nom': 'test.txt', 'base64': base64.b64encode(b'CAS FICTIF').decode()}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(serveur, 'DOSSIERS', Path(tmp)), TestClient(serveur.app) as client:
            for contenu in [texte([d[:-6] for d in periode()]), texte().replace(',12.5', '', 1),
                            texte().replace(',12.5', ',12.5,999', 1)]:
                reponse = client.post('/api/importer', json={'documents': documents, 'profil': contenu})
                self.assertEqual(reponse.status_code, 422, reponse.text)
                self.assertFalse(list(Path(tmp).glob('*.json')))
            reponse = client.post('/api/importer', json={'documents': documents, 'profil': texte()})
            self.assertEqual(reponse.status_code, 200, reponse.text)
            self.assertEqual(reponse.json()['nombre_mesures'], 96)

    def test_periode_incomplete_bloque_la_marge_et_le_rapport(self):
        dossier = {'profil_brut': [12.5] * 92, 'profil_horodatages': periode()[:-4],
                   'unite_profil': 'kw', 'kwmax_facture': 12.5, 'kwh_facture': 287.5,
                   'gtv_kw': 30, 'periode_facture_debut': '2026-09-01',
                   'periode_facture_fin': '2026-09-01', 'mesure_au_point_de_livraison': True}
        resultats = controles.executer_tous(dossier)
        self.assertEqual(next(r for r in resultats if r['id'] == 'CTRL-MARGE')['statut'], 'bloque')
        rapport = rapport_controles.composer(dossier, resultats)
        self.assertIn('MESURES NON VÉRIFIÉES', rapport_controles.en_texte(rapport))
        nl = rapport_nl.en_html(rapport)
        self.assertIn('Metingen niet bevestigd', nl)
        self.assertIn('92 metingen', nl)
        self.assertIn('96 kwartieren verwacht', nl)
        self.assertIn('de periode van de export is niet bevestigd', nl)
        self.assertNotIn('de maximale belasting van dezelfde periode ontbreekt', nl)

    def test_messages_neerlandais_sur_dates_invalides(self):
        controles = [cm.controler_periode(periode(), ('erreur', '2026-09-01'), 96),
                     cm.controler_periode([d[:-6] for d in periode()], ('2026-09-01', '2026-09-01'), 96)]
        for controle in controles:
            message, _ = rapport_nl._zin(controle)
            self.assertNotIn('Horodatage', message)
            self.assertNotIn('facturation', message)
            self.assertIn('tijd', message)


if __name__ == '__main__':
    unittest.main()
