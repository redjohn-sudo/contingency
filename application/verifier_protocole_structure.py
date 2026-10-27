"""Régressions du protocole applicatif, réponses simulées sauf essai live séparé."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import extraction_nebius as extraction
import protocole_structure as protocole


def documents():
    return [{'nom': 'contrat.txt', 'sha256': 'test', 'texte':
             'Plafond contractuel : 150 kW.\nRendement par sens : 90 %.\nDurée consécutive : 240 minutes.'}]


def reponse():
    return {'resume': 'Contraintes extraites ; autres champs absents.',
            'champs': {c: None for c in extraction.REQUETES},
            'preuves': {c: [] for c in extraction.REQUETES},
            'alertes': [], 'decision': 'demander_information'}


def avec_plafond():
    r = reponse()
    r['champs']['plafond_kw'] = 150
    r['preuves']['plafond_kw'] = [{'repere': 'D1:L1', 'citation': '150 kW'}]
    return r


def sortie(r, fin='stop'):
    return {'model': extraction.MODELE_DEFAUT, 'choices': [{'finish_reason': fin,
             'message': {'content': json.dumps(r)}}], 'usage': {'total_tokens': 10}}


class Protocole(unittest.TestCase):
    def executer(self, r, docs=None, fin='stop'):
        with patch.dict(os.environ, {'NEBIUS_API_KEY': 'factice'}, clear=True), \
                patch.object(extraction, 'appeler', return_value=(sortie(r, fin), .1)) as appel:
            resultat = extraction.extraire(docs or documents())
        self.assertEqual(appel.call_count, 1)
        self.assertEqual(appel.call_args.args[0], 'chat/completions')
        corps = appel.call_args.args[1]
        self.assertEqual(corps['max_tokens'], 6000)
        self.assertEqual(corps['reasoning_effort'], 'none')
        self.assertTrue(corps['response_format']['json_schema']['strict'])
        return resultat

    def test_valeur_citee_et_conversion(self):
        r = avec_plafond()
        r['champs']['duree_heures'] = 4
        r['preuves']['duree_heures'] = [{'repere': 'D1:L3', 'citation': '240 minutes'}]
        resultat = self.executer(r)
        self.assertEqual(resultat['propositions']['plafond_kw']['valeur'], 150)
        self.assertEqual(resultat['propositions']['duree_heures']['valeur'], 4)
        self.assertEqual(resultat['decision'], 'demander_information')

    def test_exact_displayed_reference_prefix_is_not_source_text(self):
        r=avec_plafond()
        original='D1:L1 | Plafond contractuel : 150 kW.'
        r['preuves']['plafond_kw'][0]['citation']=original
        result=self.executer(r)
        self.assertEqual(result['propositions']['plafond_kw']['valeur'],150)
        proof=result['propositions']['plafond_kw']['preuves'][0]
        self.assertTrue(proof['valide'])
        self.assertEqual(proof['citation_modele'],original)
        self.assertEqual(proof['citation'],'Plafond contractuel : 150 kW.')

    def test_prefix_does_not_excuse_wrong_reference_or_invented_quote(self):
        for quote in ['D1:L2 | Plafond contractuel : 150 kW.',
                      'D1:L1 | Plafond contractuel : 999 kW.']:
            r=avec_plafond();r['preuves']['plafond_kw'][0]['citation']=quote
            result=self.executer(r)
            self.assertIsNone(result['propositions']['plafond_kw']['valeur'])
            self.assertFalse(result['propositions']['plafond_kw']['preuves'][0]['valide'])

    def test_contradiction_null_conserve_deux_preuves(self):
        docs = [{'texte': 'Plafond contractuel : 150 kW.\nPlafond contractuel : 200 kW.'}]
        r = reponse()
        r['preuves']['plafond_kw'] = [{'repere': 'D1:L1', 'citation': '150 kW'},
                                    {'repere': 'D1:L2', 'citation': '200 kW'}]
        r['alertes'] = ['sources_contradictoires']
        resultat = self.executer(r, docs)
        p = resultat['propositions']['plafond_kw']
        self.assertIsNone(p['valeur'])
        self.assertEqual(len(p['preuves']), 2)
        self.assertTrue(all(p['valide'] for p in p['preuves']))

    def test_contradiction_ignoree_par_modele_bloquee_localement(self):
        docs = [{'texte': 'Plafond contractuel : 150 kW.\nPlafond contractuel : 200 kW.'}]
        resultat = self.executer(avec_plafond(), docs)
        self.assertIsNone(resultat['propositions']['plafond_kw']['valeur'])

    def test_citation_authentique_ne_valide_pas_un_nombre_typographique_tronque(self):
        for texte, valeur in [('Plafond réseau : −150 kW.', 150),
                              ('Plafond réseau : 1’500 kW.', 500)]:
            with self.subTest(texte=texte):
                reponse_modele = reponse()
                reponse_modele['champs']['plafond_kw'] = valeur
                reponse_modele['preuves']['plafond_kw'] = [{'repere': 'D1:L1', 'citation': texte}]
                resultat = self.executer(reponse_modele, [{'texte': texte}])
                proposition = resultat['propositions']['plafond_kw']
                self.assertIsNone(proposition['valeur'])
                self.assertEqual(proposition['valeur_proposee'], valeur)
                self.assertEqual(proposition['preuves'][0]['citation'], texte)

    def test_mauvaise_page_meme_ligne_bloquee(self):
        docs = documents()
        docs[0]['lecture_ocr'] = {'pages': [{'page': 1, 'plages_lignes': [{'debut': 1, 'fin': 3}]}]}
        r = avec_plafond()
        r['preuves']['plafond_kw'][0]['repere'] = 'D1:P2:L1'
        resultat = self.executer(r, docs)
        self.assertIsNone(resultat['propositions']['plafond_kw']['valeur'])
        self.assertEqual(resultat['propositions']['plafond_kw']['valeur_modele'], 150)
        self.assertFalse(resultat['propositions']['plafond_kw']['preuves'][0]['valide'])

    def test_page_exacte_acceptee(self):
        docs = documents()
        docs[0]['lecture_ocr'] = {'pages': [{'page': 2, 'plages_lignes': [{'debut': 1, 'fin': 3}]}]}
        r = avec_plafond()
        r['preuves']['plafond_kw'][0]['repere'] = 'D1:P2:L1'
        resultat = self.executer(r, docs)
        self.assertEqual(resultat['propositions']['plafond_kw']['valeur'], 150)
        self.assertEqual(resultat['propositions']['plafond_kw']['ligne'], 1)

    def test_preuve_invalide_sur_null_conservee_signalee(self):
        r = reponse()
        r['preuves']['rendement'] = [{'repere': 'D99:L1', 'citation': 'absent'}]
        resultat = self.executer(r)
        self.assertFalse(resultat['propositions']['rendement']['preuves'][0]['valide'])
        self.assertTrue(any('preuve invalide' in a for a in resultat['alertes']))

    def test_une_preuve_fausse_parmi_deux_bloque(self):
        r = avec_plafond()
        r['preuves']['plafond_kw'].append({'repere': 'D1:L2', 'citation': '999 kW'})
        self.assertIsNone(self.executer(r)['propositions']['plafond_kw']['valeur'])

    def test_chiffre_invente_dans_citation_vraie_bloque(self):
        r = avec_plafond()
        r['champs']['plafond_kw'] = 999
        self.assertIsNone(self.executer(r)['propositions']['plafond_kw']['valeur'])

    def test_rendement_cycle_non_converti(self):
        r = reponse()
        r['champs']['rendement'] = .88
        r['preuves']['rendement'] = [{'repere': 'D1:L1', 'citation': '88 %'}]
        resultat = self.executer(r, [{'texte': 'Rendement aller-retour : 88 %.'}])
        self.assertIsNone(resultat['propositions']['rendement']['valeur'])

    def test_decision_modele_ne_force_pas_acceptation(self):
        r = reponse()
        r['decision'] = 'extraire'
        resultat = self.executer(r)
        self.assertEqual(resultat['decision_modele'], 'extraire')
        self.assertEqual(resultat['decision'], 'demander_information')

    def test_sortie_tronquee_refusee(self):
        with self.assertRaisesRegex(ValueError, 'incomplète'):
            self.executer(reponse(), fin='length')

    def test_schema_local_refuse_sorties_deviantes(self):
        for cle, valeur in [('decision', 'approuve'), ('alertes', ['nouveau_code']),
                            ('resume', 12), ('champs', {}), ('preuves', {})]:
            with self.subTest(cle=cle):
                r = reponse(); r[cle] = valeur
                with self.assertRaises(ValueError):
                    protocole.valider_structure(r, extraction.REQUETES)
        for valeur in [True, float('nan'), -1, '150']:
            r = reponse(); r['champs']['plafond_kw'] = valeur
            with self.assertRaises(ValueError):
                protocole.valider_structure(r, extraction.REQUETES)

    def test_tout_document_conserve_ou_refus_avant_api(self):
        docs = [{'texte': '\n'.join(['Texte.'] * 500 + ['Plafond contractuel : 150 kW.'])}]
        demande, _ = protocole.preparer_demande(docs, extraction.REQUETES)
        self.assertIn('D1:L501', demande['documents'][0]['texte'])
        with patch.object(protocole, 'LIMITE_CONTEXTE', 100), patch.object(extraction, 'appeler') as appel:
            with self.assertRaisesRegex(ValueError, 'volumineux'):
                extraction.extraire(docs)
            appel.assert_not_called()

    def test_cache_change_avec_modele_reglages_texte_pages(self):
        docs = documents()
        with patch.dict(os.environ, {}, clear=True):
            initiale = extraction.empreinte_extraction(docs)
            with patch.dict(os.environ, {'NEBIUS_MAX_TOKENS': '20000'}):
                self.assertNotEqual(initiale, extraction.empreinte_extraction(docs))
            with patch.dict(os.environ, {'NEBIUS_CHAT_MODEL': 'autre-modele'}):
                self.assertNotEqual(initiale, extraction.empreinte_extraction(docs))
            autre = copy.deepcopy(docs); autre[0]['texte'] += '\nNouvelle ligne.'
            self.assertNotEqual(initiale, extraction.empreinte_extraction(autre))
            autre = copy.deepcopy(docs); autre[0]['nom'] = 'guide.txt'
            self.assertNotEqual(initiale, extraction.empreinte_extraction(autre))
            autre = copy.deepcopy(docs); autre[0]['type_document'] = 'hypothese_simulation'
            self.assertNotEqual(initiale, extraction.empreinte_extraction(autre))
            autre = copy.deepcopy(docs)
            autre[0]['lecture_ocr'] = {'pages': [{'page': 2, 'plages_lignes': [{'debut': 1, 'fin': 3}]}]}
            self.assertNotEqual(initiale, extraction.empreinte_extraction(autre))


class IntegrationHTTP(unittest.TestCase):
    def test_endpoint_cache_export_et_aucune_application_automatique(self):
        import serveur
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as repertoire, patch.object(serveur, 'DOSSIERS', Path(repertoire)), \
                patch.dict(os.environ, {'NEBIUS_API_KEY': 'factice'}, clear=True), \
                patch.object(extraction, 'appeler', return_value=(sortie(reponse()), .1)) as appel:
            client = TestClient(serveur.app)
            dossier = client.post('/api/exemple').json()
            url = f'/api/{dossier["id"]}/extraire'
            resultat = client.post(url)
            self.assertEqual(resultat.status_code, 200, resultat.text)
            self.assertEqual(resultat.json()['faits'], dossier['faits'])
            self.assertEqual(resultat.json()['extraction_ia']['decision'], 'demander_information')
            client.post(url)
            self.assertEqual(appel.call_count, 1)
            with patch.dict(os.environ, {'NEBIUS_MAX_TOKENS': '20000'}):
                self.assertEqual(client.post(url).status_code, 200)
            self.assertEqual(appel.call_count, 2)
            export = client.get(f'/api/{dossier["id"]}/donnees').json()
            self.assertIn('preuves', export['extraction_ia']['propositions']['plafond_kw'])


if __name__ == '__main__':
    unittest.main()
