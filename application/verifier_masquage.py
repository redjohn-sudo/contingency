"""Données personnelles masquées avant tout envoi au fournisseur de modèle (issue n° 12)."""
import copy
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import extraction_fiche as ef
import extraction_nebius as extraction
import lancer_demo_archivee
import masquage
import protocole_structure as protocole
import serveur
from verifier_contradictions import reponse
from verifier_protocole_structure import avec_plafond, documents as documents_protocole, sortie as sortie_modele


class Masquage(unittest.TestCase):
    def test_iban(self):
        for texte in ['Betaal op IBAN NL91 ABNA 0417 1643 00 ten name van Liander', 'IBAN:FR7630006000011234567890189']:
            with self.subTest(texte=texte):
                masque = masquage.masquer(texte)
                self.assertIn('[IBAN]', masque)
                self.assertNotIn('0417', masque)
                self.assertNotIn('1234567890', masque)

    def test_iban_coupe_sur_deux_lignes(self):
        texte = 'Betaal op IBAN NL91 ABNA\n0417 1643 00 ten name van Liander\nPlafond : 150 kW'
        masque = masquage.masquer(texte)
        self.assertNotIn('0417', masque)
        self.assertNotIn('ABNA', masque)
        self.assertEqual(len(masque.splitlines()), 3)
        self.assertEqual(masque.splitlines()[2], 'Plafond : 150 kW')

    def test_email(self):
        self.assertEqual(masquage.masquer('Contact : jan.de-vries@bedrijf.nl.'), 'Contact : [EMAIL].')

    def test_telephones(self):
        for numero in ['+31 6 12345678', '06-12345678', '020-1234567', '(020) 1234567', '+33 6 12 34 56 78', '01 23 45 67 89', '0031 20 123 4567']:
            with self.subTest(numero=numero):
                self.assertEqual(masquage.masquer('Tel. ' + numero + ' (support)'), 'Tel. [TEL] (support)')

    def test_bsn_nomme_ou_preuve_de_onze(self):
        for texte, attendu in [('BSN 111222333', 'BSN [BSN]'), ('Klant 012345672 akkoord', 'Klant [BSN] akkoord'),
                               ('BSN: 12345672', 'BSN: [BSN]'), ('Burgerservicenummer 123456789', 'Burgerservicenummer [BSN]')]:
            with self.subTest(texte=texte):
                self.assertEqual(masquage.masquer(texte), attendu)
        for texte in ['Dossier 123456789', 'Compteur 000000000', 'Commande 12345672', 'Prix 111222333 EUR', 'Prix : € 111222333',
                      'Totaal 111222333 kWh', 'Pointe 111222333 kW', 'Part 111222333 %']:
            with self.subTest(texte=texte):
                self.assertEqual(masquage.masquer(texte), texte)

    def test_ean_et_kvk_seulement_quand_nommes(self):
        self.assertEqual(masquage.masquer('EAN-code: 871687400008745671'), 'EAN-code: [EAN]')
        self.assertEqual(masquage.masquer('KvK 12345678'), 'KvK [KVK]')
        for texte in ['Référence 871687400008745671', 'Commande 12345678']:
            with self.subTest(texte=texte):
                self.assertEqual(masquage.masquer(texte), texte)

    def test_secrets(self):
        for secret in ['sk-EXAMPLE-not-a-real-key', 'sk-proj-AbCdEf1234567890XyZaBc', 'ghp_EXAMPLEnotarealtoken000',
                       'AKIAIOSFODNN7EXAMPLE', 'xoxb-1234567890-abcdefghijkl']:
            with self.subTest(secret=secret):
                self.assertEqual(masquage.masquer('cle = ' + secret), 'cle = [SECRET]')
        self.assertEqual(masquage.masquer('Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def'), 'Authorization: Bearer [SECRET]')
        self.assertEqual(masquage.masquer('DATABASE_URL=postgres://app:pw@localhost/app'), 'DATABASE_URL=postgres://[SECRET]@localhost/app')

    def test_valeurs_techniques_intactes(self):
        lignes = ['Plafond contractuel : 15 000 kW.', 'Plafond contractuel : 0,65 MW.', 'Rendement par sens : 90 %.',
                  'Mag alleen draaien tussen 08:00 en 18:00.', 'Montant : 1 234,56 €', 'Factuurdatum: 02-09-2026',
                  'Durée consécutive : 240 minutes.', 'kWmax 595 kW op 04-01-2016 12:15',
                  '2016-01-01T00:15:00+01:00,595', 'Afgenomen belasting 31/31 maa 344 kW', '31-03-2018 Verbruik laag 50.137 kWh laag']
        for ligne in lignes:
            with self.subTest(ligne=ligne):
                self.assertEqual(masquage.masquer(ligne), ligne)

    def test_lignes_conservees(self):
        texte = 'Plafond : 150 kW\nIBAN NL91 ABNA 0417 1643 00\nTel. 06-12345678\n'
        self.assertEqual(len(masquage.masquer(texte).splitlines()), len(texte.splitlines()))

    def test_compte_sans_valeurs(self):
        texte, compte = masquage.masquer_compter('IBAN NL91ABNA0417164300, mail a@b.nl, a2@b.nl')
        self.assertEqual(compte, {'IBAN': 1, 'EMAIL': 2})
        self.assertNotIn('a@b.nl', json.dumps(compte))


class Envoi(unittest.TestCase):
    def envoyer(self, corps):
        envoye = {}

        class Reponse(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): return False

        def urlopen(requete, timeout):
            envoye['corps'] = json.loads(requete.data.decode())
            return Reponse(json.dumps({'ok': True}).encode())

        with patch('urllib.request.urlopen', urlopen):
            sortie, _ = extraction.appeler('chat/completions', corps, 'cle')
        return envoye['corps'], sortie

    def test_appeler_masque_messages_et_entrees(self):
        corps = {'messages': [{'role': 'user', 'content': 'Contrat. IBAN NL91 ABNA 0417 1643 00, contact jan@bedrijf.nl'}],
                 'input': ['Tel. 06-12345678', 'Plafond contractuel : 150 kW.']}
        avant = copy.deepcopy(corps)
        envoye, sortie = self.envoyer(corps)
        texte = json.dumps(envoye)
        self.assertNotIn('0417', texte)
        self.assertNotIn('jan@bedrijf.nl', texte)
        self.assertNotIn('12345678', texte)
        self.assertIn('Plafond contractuel : 150 kW.', texte)
        self.assertEqual(corps, avant, 'le corps de l’appelant ne doit pas être modifié')
        self.assertEqual(sortie['masquage'], {'IBAN': 1, 'EMAIL': 1, 'TEL': 1})

    def test_comptes_independants_entre_appels_simultanes(self):
        from concurrent.futures import ThreadPoolExecutor
        corps = [{'messages': [{'role': 'user', 'content': 'mail a@b.nl'}]},
                 {'messages': [{'role': 'user', 'content': 'IBAN NL91ABNA0417164300 et 06-12345678'}]},
                 {'messages': [{'role': 'user', 'content': 'Plafond : 150 kW'}]}] * 5
        with ThreadPoolExecutor(3) as ex:
            sorties = list(ex.map(lambda c: self.envoyer(c)[1], corps))
        attendus = [{'EMAIL': 1}, {'IBAN': 1, 'TEL': 1}, {}] * 5
        self.assertEqual([s['masquage'] for s in sorties], attendus)

    def test_schema_et_parametres_intacts(self):
        corps = {'model': 'deepseek-ai/DeepSeek-V4.1-Flash', 'temperature': 0,
                 'messages': [{'role': 'system', 'content': 'Réponds en JSON.'}],
                 'response_format': {'type': 'json_schema', 'json_schema': {'schema': {'enum': ['support@exemple.nl']}}}}
        envoye, _ = self.envoyer(corps)
        self.assertEqual(envoye['response_format'], corps['response_format'])
        self.assertEqual(envoye['model'], corps['model'])

    def test_version_du_masquage_dans_la_configuration(self):
        self.assertEqual(extraction.configuration()['masquage'], masquage.VERSION)

    def test_demo_archivee_toujours_rejouable(self):
        dossiers, extracteur = serveur.DOSSIERS, serveur.extraire_avec_nebius
        try:
            with tempfile.TemporaryDirectory() as rep:
                lancer_demo_archivee.configurer(rep)
        finally:
            serveur.DOSSIERS, serveur.extraire_avec_nebius = dossiers, extracteur


class Citations(unittest.TestCase):
    def test_extraction_citation_avec_etiquette(self):
        docs = [{'nom': 'contrat.txt', 'texte': 'Plafond contractuel : 150 kW, contact jan@bedrijf.nl.'}]
        propositions, _ = extraction.controler_propositions(
            reponse('plafond_kw', 150, 'Plafond contractuel : 150 kW, contact [EMAIL].'), docs)
        self.assertEqual(propositions['plafond_kw']['valeur'], 150)

    def test_extraction_faux_secret_dans_la_citation_refuse(self):
        docs = [{'nom': 'contrat.txt', 'texte': 'Plafond contractuel : 150 kW.'}]
        propositions, _ = extraction.controler_propositions(
            reponse('plafond_kw', 150, 'Plafond contractuel : 150 kW, contact jan@bedrijf.nl'), docs)
        self.assertIsNone(propositions['plafond_kw']['valeur'])

    def test_autre_email_dans_la_citation_refuse(self):
        docs = [{'nom': 'contrat.txt', 'texte': 'Plafond contractuel : 150 kW, contact jan@bedrijf.nl.'}]
        propositions, _ = extraction.controler_propositions(
            reponse('plafond_kw', 150, 'Plafond contractuel : 150 kW, contact piet@bedrijf.nl.'), docs)
        self.assertIsNone(propositions['plafond_kw']['valeur'])

    def test_un_bsn_ne_fournit_pas_de_valeur(self):
        docs = [{'nom': 'contrat.txt', 'texte': 'Plafond contractuel : 150 kW, klant 111222333.'}]
        propositions, _ = extraction.controler_propositions(
            reponse('plafond_kw', 111222333, 'Plafond contractuel : 150 kW, klant [BSN].'), docs)
        self.assertIsNone(propositions['plafond_kw']['valeur'])

    def test_documents_non_modifies(self):
        docs = [{'nom': 'contrat.txt', 'sha256': 'x', 'texte': 'Plafond contractuel : 150 kW, contact jan@bedrijf.nl.'}]
        avant = copy.deepcopy(docs)
        extraction.controler_propositions(reponse('plafond_kw', 150, 'Plafond contractuel : 150 kW, contact [EMAIL].'), docs)
        self.assertEqual(docs, avant)

    def test_un_telephone_ne_fournit_pas_de_valeur(self):
        docs = [{'nom': 'contrat.txt', 'texte': 'Plafond contractuel : voir 020-1234567 kW.'}]
        propositions, _ = extraction.controler_propositions(
            reponse('plafond_kw', 1234567, 'Plafond contractuel : voir [TEL] kW.'), docs)
        self.assertIsNone(propositions['plafond_kw']['valeur'])

    def test_fiche_citation_avec_etiquette(self):
        documents = [{'nom': 'ATO', 'texte': 'Gecontracteerd transportvermogen 347 kW, contact jan@bedrijf.nl'}]
        index = ef.indexer(documents)
        repere = next(iter(index))
        champs = {c: None for c in ef.CHAMPS}
        preuves = {c: [] for c in ef.CHAMPS}
        champs['gtv_declare_kw'] = 347
        preuves['gtv_declare_kw'] = [{'repere': repere, 'citation': 'Gecontracteerd transportvermogen 347 kW, contact [EMAIL]'}]
        r = ef.controler({'resume': '', 'champs': champs, 'preuves': preuves, 'alertes': []}, documents, index)
        self.assertEqual(r['valeurs']['gtv_declare_kw']['valeur'], 347)

    def test_protocole_citation_avec_etiquette(self):
        documents = [{'nom': 'contrat.txt', 'texte': 'Plafond contractuel : 150 kW, contact jan@bedrijf.nl.'}]
        champs = {c: None for c in extraction.REQUETES}
        preuves = {c: [] for c in extraction.REQUETES}
        champs['plafond_kw'] = 150
        preuves['plafond_kw'] = [{'repere': 'D1:L1', 'citation': 'Plafond contractuel : 150 kW, contact [EMAIL].'}]
        demande = {'resume': '', 'champs': champs, 'preuves': preuves, 'alertes': [], 'decision': protocole.DECISIONS[0]}
        adaptee, _ = protocole.adapter_propositions(demande, documents, extraction.REQUETES, extraction.controler_valeur)
        plafond = next(p for p in adaptee['propositions'] if p['champ'] == 'plafond_kw')
        self.assertEqual(plafond['valeur'], 150)



class Journaux(unittest.TestCase):
    """Les comptes de masquage restent dans les journaux des trois envois réels (revue d'Astra, M3)."""

    def test_journal_des_embeddings(self):
        class Reponse(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): return False

        def urlopen(requete, timeout):
            entrees = json.loads(requete.data.decode())['input']
            donnees = [{'index': i, 'embedding': [1.0, (i % 3) + .5]} for i in range(len(entrees))]
            return Reponse(json.dumps({'data': donnees, 'usage': {'total_tokens': 1}}).encode())

        docs = [{'nom': 'contrat.txt', 'texte': 'Plafond contractuel : 150 kW.\nContact : jan@bedrijf.nl'}]
        with patch('urllib.request.urlopen', urlopen):
            _, methode, journal = extraction.choisir_contextes(extraction.passages_documents(docs), 'cle')
        self.assertEqual(methode, 'hybride_lexical_semantique')
        self.assertEqual(journal[0]['masquage'], {'EMAIL': 1})

    def test_journal_de_l_extraction(self):
        s = sortie_modele(avec_plafond())
        s['masquage'] = {'IBAN': 1}
        with patch.dict(os.environ, {'NEBIUS_API_KEY': 'factice'}, clear=True), \
                patch.object(extraction, 'appeler', return_value=(s, .1)):
            resultat = extraction.extraire(documents_protocole())
        self.assertEqual(resultat['journal_api'][0]['masquage'], {'IBAN': 1})

    def test_journal_de_la_fiche(self):
        champs = {c: None for c in ef.CHAMPS}
        preuves = {c: [] for c in ef.CHAMPS}
        contenu = json.dumps({'resume': '', 'champs': champs, 'preuves': preuves, 'alertes': []})
        s = {'model': ef.MODELE, 'choices': [{'finish_reason': 'stop', 'message': {'content': contenu}}], 'masquage': {'TEL': 2}}
        with patch.object(extraction, 'charger_cle', return_value='cle'), patch.object(extraction, 'appeler', return_value=(s, .1)):
            resultat = ef.extraire([{'nom': 'ATO', 'texte': 'Gecontracteerd transportvermogen 347 kW'}])
        self.assertEqual(resultat['journal']['masquage'], {'TEL': 2})



class DocumentsMasquesAvantEnvoi(unittest.TestCase):
    """M4 (revue d'Astra) : un identifiant coupé entre deux lignes est masqué avant la mise en JSON et les repères."""
    TEXTE = 'Plafond contractuel : 150 kW, rekening NL91 ABNA\n0417 1643 00 ten name van Liander\nRendement par sens : 90 %.'

    def capturer(self, reponse_modele):
        corps = []

        class Reponse(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): return False

        def urlopen(requete, timeout):
            corps.append(requete.data.decode())
            return Reponse(json.dumps(reponse_modele).encode())
        return corps, urlopen

    def verifier_corps(self, corps):
        self.assertTrue(corps)
        for texte in corps:
            self.assertNotIn('ABNA', texte)
            self.assertNotIn('0417', texte)

    def test_extraction(self):
        docs = [{'nom': 'contrat.txt', 'sha256': 'x', 'texte': self.TEXTE}]
        corps, urlopen = self.capturer(sortie_modele(avec_plafond()))
        with patch.dict(os.environ, {'NEBIUS_API_KEY': 'factice'}, clear=True), patch('urllib.request.urlopen', urlopen):
            resultat = extraction.extraire(docs)
        self.verifier_corps(corps)
        self.assertEqual(resultat['propositions']['plafond_kw']['valeur'], 150)
        self.assertEqual(docs[0]['texte'], self.TEXTE, 'le document local reste intact')

    def test_fiche(self):
        champs = {c: None for c in ef.CHAMPS}
        preuves = {c: [] for c in ef.CHAMPS}
        contenu = json.dumps({'resume': '', 'champs': champs, 'preuves': preuves, 'alertes': []})
        corps, urlopen = self.capturer({'model': ef.MODELE, 'choices': [{'finish_reason': 'stop', 'message': {'content': contenu}}]})
        with patch.object(extraction, 'charger_cle', return_value='cle'), patch('urllib.request.urlopen', urlopen):
            ef.extraire([{'nom': 'ATO', 'texte': self.TEXTE}])
        self.verifier_corps(corps)

    def test_passages(self):
        passages = extraction.passages_documents([{'nom': 'contrat.txt', 'texte': self.TEXTE}])
        self.verifier_corps([json.dumps(passages)])

    def test_vue_masquee_garde_les_lignes(self):
        masques = masquage.documents_masques([{'nom': 'a', 'texte': self.TEXTE}])
        self.assertEqual(len(masques[0]['texte'].splitlines()), 3)
        self.assertEqual(masques[0]['texte'].splitlines()[0], 'Plafond contractuel : 150 kW, rekening [IBAN]')


if __name__ == '__main__':
    unittest.main()
