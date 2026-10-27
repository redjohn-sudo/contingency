"""Mesures acoustiques complètes avant conclusion, sans réseau."""
import copy
import json
import unittest

import controles
import rapport_controles
import rapport_nl


def dossier():
    return {
        'commune': 'Dordrecht', 'chimie_batterie': 'lithium',
        'capacite_kwh': 2000., 'puissance_kw': 500.,
        'date_mise_en_service': None, 'terrain_industriel_zone': False,
        'bruit_facade_db': {'jour': 40., 'soir': 35., 'nuit': 30.},
    }


def bruit(entree):
    return next(r for r in controles.executer_tous(entree) if r['id'] == 'CTRL-BRUIT-COMMUNE')


class EntreesBruit(unittest.TestCase):
    def bloque(self, resultat):
        self.assertEqual(resultat['statut'], 'bloque', resultat)
        self.assertNotIn('mesures_db', resultat.get('valeurs', {}))
        self.assertNotIn('seuils_db', resultat.get('valeurs', {}))
        self.assertNotIn('sous les seuils', resultat['constat'])
        json.dumps(resultat, allow_nan=False)

    def test_chaque_periode_manquante_bloque(self):
        for moment in ('jour', 'soir', 'nuit'):
            for absence in ('absente', None):
                with self.subTest(moment=moment, absence=absence):
                    entree = dossier()
                    if absence == 'absente':
                        del entree['bruit_facade_db'][moment]
                    else:
                        entree['bruit_facade_db'][moment] = None
                    for resultat in (bruit(entree), controles.bruit_commune(entree)):
                        self.bloque(resultat)
                        self.assertEqual(resultat['valeurs']['raison'], 'mesures_bruit_incompletes')
                        self.assertIn(moment, resultat['valeurs']['periodes'])

    def test_mesure_de_jour_seule_ne_conclut_plus_pour_la_nuit(self):
        entree = dossier(); entree['bruit_facade_db'] = {'jour': 40.}
        resultat = bruit(entree)
        self.bloque(resultat)
        self.assertEqual(resultat['valeurs']['periodes'], ['soir', 'nuit'])
        self.assertIn('geen conclusie', rapport_nl._zin(resultat)[0])

    def test_conteneur_invalide_ne_fait_pas_planter(self):
        for mesures in (None, False, True, 40, '40', [], [40, 35, 30], {}, {'autre': 30}):
            with self.subTest(mesures=mesures):
                entree = dossier(); entree['bruit_facade_db'] = mesures
                self.bloque(bruit(entree))
                self.bloque(controles.bruit_commune(entree))

    def test_nombres_invalides_refuses_pour_chaque_periode(self):
        invalides = (False, True, '30', '', [], {}, float('nan'), float('inf'), -float('inf'), 10**400)
        for moment in ('jour', 'soir', 'nuit'):
            for valeur in invalides:
                with self.subTest(moment=moment, valeur=repr(valeur)):
                    entree = dossier(); entree['bruit_facade_db'][moment] = valeur
                    resultat = bruit(entree)
                    self.bloque(resultat)
                    self.assertEqual(resultat['valeurs']['raison'], 'mesures_bruit_invalides')
                    self.assertEqual(resultat['valeurs']['periodes'], [moment])
                    rapport = rapport_controles.composer(entree)
                    json.dumps(rapport, allow_nan=False)
                    self.assertTrue(rapport_controles.en_html(rapport))
                    self.assertIn('Ongeldige geluidgegevens', rapport_nl.en_html(rapport))

    def test_mesures_completes_inferieures_egales_ou_superieures(self):
        for mesures, statut in (({'jour': 40., 'soir': 35., 'nuit': 30.}, 'constat'),
                                ({'jour': 45., 'soir': 40., 'nuit': 35.}, 'constat'),
                                ({'jour': 45., 'soir': 40., 'nuit': 35.1}, 'alerte')):
            entree = dossier(); entree['bruit_facade_db'] = mesures
            resultat = bruit(entree)
            self.assertEqual(resultat['statut'], statut)
            self.assertEqual(resultat['valeurs']['mesures_db'], mesures)
            texte = rapport_nl._zin(resultat)[0]
            self.assertTrue(all(nom in texte for nom in ('dag:', 'avond:', 'nacht:')))
            self.assertEqual('overschreden' in texte, statut == 'alerte')

    def test_zero_et_decibels_negatifs_sont_des_nombres_valides(self):
        entree = dossier(); entree['bruit_facade_db'] = {'jour': 0., 'soir': -1., 'nuit': -5.}
        resultat = bruit(entree)
        self.assertEqual(resultat['statut'], 'constat')
        self.assertEqual(resultat['valeurs']['mesures_db']['nuit'], -5.)

    def test_classement_du_terrain_exige_un_booleen(self):
        for terrain in (None, 0, 1, 'false', 'true', 'non', [], {}, float('nan')):
            with self.subTest(terrain=repr(terrain)):
                entree = dossier(); entree['terrain_industriel_zone'] = terrain
                self.bloque(bruit(entree))
                resultat = controles.bruit_commune(entree)
                self.bloque(resultat)
                self.assertEqual(resultat['valeurs']['raison'], 'terrain_bruit_invalide')

    def test_exception_terrain_ne_valide_pas_les_mesures(self):
        entree = dossier()
        entree.update(terrain_industriel_zone=True, bruit_facade_db={'jour': float('nan')})
        resultat = bruit(entree)
        self.assertEqual(resultat['statut'], 'constat')
        self.assertIn('exception', resultat['valeurs'])
        self.assertNotIn('mesures_db', resultat['valeurs'])
        self.assertNotIn('seuils_db', resultat['valeurs'])
        self.assertIn('omgevingsplan', rapport_nl._zin(resultat)[0])
        json.dumps(rapport_controles.composer(entree), allow_nan=False)

    def test_hors_champ_ne_revendique_aucun_chiffre(self):
        entree = dossier()
        entree.update(chimie_batterie='sodium', bruit_facade_db={'jour': float('nan')})
        resultat = bruit(entree)
        self.assertEqual(resultat['champ_d_application']['statut'], 'hors_champ')
        self.assertNotIn('valeurs', resultat)
        json.dumps(rapport_controles.composer(entree), allow_nan=False)

    def test_annotations_non_utilisees_et_dossier_preserve(self):
        entree = dossier()
        entree['bruit_facade_db']['annotation'] = {'valeur': float('nan')}
        avant = json.dumps(entree, sort_keys=True)
        resultat = bruit(entree)
        self.assertEqual(set(resultat['valeurs']['mesures_db']), {'jour', 'soir', 'nuit'})
        self.assertEqual(avant, json.dumps(entree, sort_keys=True))
        json.dumps(rapport_controles.composer(copy.deepcopy(entree)), allow_nan=False)


if __name__ == '__main__':
    unittest.main()
