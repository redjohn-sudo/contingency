"""Régressions de la revue : rapport NL, texte documentaire et imports refusés."""
import base64
import copy
import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import controles
import documents
import protocole_structure
import rapport_controles
import rapport_nl
import serveur
from rapport_html import rendre_rapport
from verifier_ocr import fabriquer_pdf


class RevueNeerlandais(unittest.TestCase):
    def test_05_seuils_dates_et_annee_sans_repr_ni_francais(self):
        dossier = {'commune': 'Dordrecht', 'chimie_batterie': 'LFP',
                   'capacite_kwh': 2000, 'puissance_kw': 900, 'date_mise_en_service': None,
                   'date_demande': '2026-01-01', 'date_offre': '2026-02-01',
                   'date_signature': '2026-03-01', 'date_depot': '2026-05-01',
                   'gestionnaire': 'enexis', 'annee_liberation_annoncee': 2030}
        resultats = [fonction(dossier) for fonction in (
            controles.seuil_permis, controles.delai_offre, controles.regime_depot)]
        texte = rapport_nl.en_html(rapport_controles.composer(dossier, resultats))
        for interdit in ('jours_demande_offre', 'seuils_franchis', 'regime_anterieur',
                         'True', 'False', '2.030', 'permis communal obligatoire'):
            self.assertNotIn(interdit, texte)
        for attendu in ('2030', '31 dagen', '28 dagen', '400 MWh', '800 kW', 'Enexis'):
            self.assertIn(attendu, texte)

    def test_05_repli_ne_publie_pas_les_valeurs_brutes(self):
        texte, _ = rapport_nl._zin({'id': 'CTRL-INCONNU', 'statut': 'constat',
                                    'valeurs': {'obligatoire': ['français', True]}})
        self.assertIn('Franse versie', texte)
        for interdit in ('obligatoire', 'français', 'True', '['):
            self.assertNotIn(interdit, texte)

    def test_05_chimie_et_sur_mesure_repris_sans_fausse_obligation(self):
        for chimie, capacite, attendu in (('sodium-ion', 2000, 'buiten het lithiumbereik'),
                                         ('LFP', 500000, 'risicoanalyse op maat')):
            with self.subTest(chimie=chimie):
                resultat = controles.seuil_permis({'capacite_kwh': capacite, 'puissance_kw': 500,
                    'chimie_batterie': chimie, 'commune': 'Dordrecht', 'date_mise_en_service': None})
                texte, _ = rapport_nl._zin(resultat)
                self.assertIn(attendu, texte)
                self.assertNotIn('seuils_franchis', texte)

    def test_05_booleens_et_annees(self):
        self.assertEqual(rapport_nl._waarde('annee_liberation_annoncee', 2030), '2030')
        self.assertEqual(rapport_nl._waarde('annee_liberation_annoncee', 2030.0), '2030')
        self.assertEqual(rapport_nl._waarde('condition', True), 'ja')
        self.assertEqual(rapport_nl._waarde('condition', False), 'nee')

    def test_05_blocages_nouveaux_ont_des_libelles_neerlandais(self):
        dossier = {'date_depot': '2026-05-01', 'gestionnaire': 'Stedin',
                   'capacite_kwh': 2000, 'puissance_kw': 500, 'commune': 'Dordrecht'}
        resultats = [controles.regime_depot(dossier), controles.seuil_permis(dossier)]
        texte = rapport_nl.en_html(rapport_controles.composer(dossier, resultats))
        for interdit in ('regime_depot_gestionnaire', 'chimie_batterie', 'date_mise_en_service'):
            self.assertNotIn(interdit, texte)
        self.assertIn('Batterijchemie', texte)
        self.assertIn('Regime van de aanvraag', texte)


class RevueRapportEtImport(unittest.TestCase):
    def setUp(self):
        self.temporaire = tempfile.TemporaryDirectory()
        self.racine = Path(self.temporaire.name)
        self.stockage = patch.object(serveur, 'DOSSIERS', self.racine)
        self.stockage.start()
        self.client = TestClient(serveur.app)
        self.dossier = self.client.post('/api/exemple').json()
        self.profil = 'fin_intervalle,puissance_kw\n' + ''.join(
            f'2026-01-{1 + (quart == 96):02d}T{quart // 4 % 24:02d}:{quart % 4 * 15:02d}:00Z,60\n'
            for quart in range(1, 97))
        self.pdf = fabriquer_pdf([{'textes': ['Contrat de test 150 kW']}])

    def tearDown(self):
        self.client.close()
        self.stockage.stop()
        self.temporaire.cleanup()

    def piece(self, nom='contrat.pdf', donnees=None):
        return {'nom': nom, 'base64': base64.b64encode(self.pdf if donnees is None else donnees).decode()}

    def fichiers(self):
        return {str(f.relative_to(self.racine)): f.read_bytes()
                for f in self.racine.rglob('*') if f.is_file()}

    def test_16_noms_avec_separateurs_refuses(self):
        for separateur in ('\n', '\r', '\v', '\f', '\x85', '\x1c', '\x1d', '\x1e', '\u2028', '\u2029'):
            with self.subTest(separateur=repr(separateur)):
                reponse = self.client.post('/api/importer', json={
                    'documents': [self.piece('contrat' + separateur + '## Faux.txt', b'150 kW')],
                    'profil': self.profil})
                self.assertEqual(reponse.status_code, 422)

    def test_16_ancien_dossier_et_preuve_modele_ne_creent_aucune_section(self):
        identifiant = self.dossier['id']
        reponse = self.client.post(f'/api/{identifiant}/preparer', json={'faits': self.dossier['faits']})
        reponse = self.client.post(f'/api/{identifiant}/calculer', json={
            'revision': reponse.json()['revision'], 'validation': True})
        self.assertEqual(reponse.status_code, 200, reponse.text)
        original = serveur.charger(identifiant)
        titres = re.findall(r'^##? .*', serveur.rapport(identifiant).body.decode(), flags=re.M)
        for separateur in ('\n', '\r', '\v', '\f', '\x85', '\x1c', '\x1d', '\x1e', '\u2028', '\u2029'):
            with self.subTest(separateur=repr(separateur)):
                dossier = copy.deepcopy(original)
                poison = separateur + '## Faux verdict' + separateur + '| Faux |'
                dossier['documents'][0]['nom'] += poison
                dossier['faits']['plafond_kw']['motif'] = poison
                dossier['extraction_ia'] = {'modele': 'simulé', 'empreinte': 'test',
                    'methode_recherche': poison, 'propositions': {'plafond_kw': {'preuves': [
                        {'repere': 'D1:L1' + poison, 'citation': poison, 'valide': False}]}}}
                serveur.sauver(dossier)
                texte = serveur.rapport(identifiant).body.decode()
                self.assertEqual(re.findall(r'^##? .*', texte, flags=re.M), titres)
                self.assertNotIn('<h2>Faux verdict</h2>', rendre_rapport(texte, identifiant))
                self.assertIn('preuve refusée', texte)

    def test_16_repere_invalide_est_neutralise_et_trace(self):
        repere = 'D1:L1\n## Faux verdict'
        reponse = {'resume': '', 'champs': {'plafond_kw': 150},
                   'preuves': {'plafond_kw': [{'repere': repere, 'citation': '150 kW'}]},
                   'alertes': [], 'decision': 'extraire'}
        _, preuves = protocole_structure.adapter_propositions(
            reponse, [{'nom': 'test.txt', 'texte': '150 kW'}], ['plafond_kw'], lambda *args: (True, ''))
        preuve = preuves['plafond_kw'][0]
        self.assertFalse(preuve['valide'])
        self.assertEqual(preuve['repere'], '[repère invalide]')
        self.assertEqual(preuve['repere_modele'], repere)

    def test_17_pdf_trop_long_ne_reste_pas_sur_disque(self):
        avant = self.fichiers()
        with self.assertRaisesRegex(ValueError, '60 pages'):
            documents.lire_pdf(fabriquer_pdf([{'textes': ['150 kW']}] * 61), stockage=self.racine)
        self.assertEqual(self.fichiers(), avant)

    def test_17_profil_invalide_refuse_avant_lecture_pdf(self):
        avant = self.fichiers()
        with patch.object(serveur, 'lire_pdf') as lecture:
            reponse = self.client.post('/api/importer', json={'documents': [self.piece()], 'profil': 'invalide'})
        self.assertEqual(reponse.status_code, 422)
        lecture.assert_not_called()
        self.assertEqual(self.fichiers(), avant)

    def test_17_deuxieme_piece_refusee_ne_conserve_pas_la_premiere(self):
        avant = self.fichiers()
        caches = []
        def lecture_structuree(donnees, texte, cache):
            caches.append(cache)
            cache.mkdir()
            (cache / 'lecture.json').write_text(texte)
            return {'statut': 'extrait_a_verifier', 'message': 'test'}
        with patch.object(serveur, 'completer', side_effect=lecture_structuree):
            reponse = self.client.post('/api/importer', json={
                'documents': [self.piece(), self.piece('interdit.exe', b'x')], 'profil': self.profil})
        self.assertEqual(reponse.status_code, 422)
        self.assertEqual(self.fichiers(), avant)
        self.assertTrue(caches)
        self.assertTrue(all(not cache.exists() for cache in caches))

    def test_17_import_accepte_conserve_source_et_refus_preserve_existant(self):
        with patch.object(serveur, 'completer', return_value={'statut': 'indisponible', 'message': 'test'}):
            reponse = self.client.post('/api/importer', json={'documents': [self.piece()], 'profil': self.profil})
            self.assertEqual(reponse.status_code, 200, reponse.text)
            source = reponse.json()['documents'][0]['source_pdf']
            self.assertEqual((self.racine / source['chemin']).read_bytes(), self.pdf)
            self.assertEqual(source['sha256'], hashlib.sha256(self.pdf).hexdigest())
            avant = self.fichiers()
            reponse = self.client.post('/api/importer', json={
                'documents': [self.piece(), self.piece('refus.exe', b'x')], 'profil': self.profil})
        self.assertEqual(reponse.status_code, 422)
        self.assertEqual(self.fichiers(), avant)

    def test_17_remplacement_hors_limite_refuse_avant_lecture(self):
        avant = self.fichiers()
        with patch.object(serveur, 'lire_pdf') as lecture:
            reponse = self.client.post(f"/api/{self.dossier['id']}/documents", json={
                'documents': [self.piece()] * 20})
        self.assertEqual(reponse.status_code, 422)
        lecture.assert_not_called()
        self.assertEqual(self.fichiers(), avant)

    def test_17_remplacement_refuse_ne_conserve_pas_la_premiere_piece(self):
        avant = self.fichiers()
        with patch.object(serveur, 'completer', return_value={'statut': 'indisponible', 'message': 'test'}):
            reponse = self.client.post(f"/api/{self.dossier['id']}/documents", json={
                'documents': [self.piece(), self.piece('refus.exe', b'x')]})
        self.assertEqual(reponse.status_code, 422)
        self.assertEqual(self.fichiers(), avant)


if __name__ == '__main__':
    unittest.main()
