"""Fiche à documenter : aucune valeur inconnue n'est remplacée par zéro."""
from datetime import date


def a_verifier(valeur=None):
    return {'valeur': valeur, 'source': '', 'statut': 'a_verifier',
            'verifie_par': '', 'date_verification': None}


def modele_contrats(empreinte=None, annee_mesuree=None):
    def tarif():
        return a_verifier({'gestionnaire': None, 'categorie': None, 'categorie_code': None,
                           'assiette_pointes': None, 'annee': date.today().year,
                           'contrat_eur_kw_an': None, 'pointe_eur_kw_mois': None,
                           'energie_eur_kwh': None, 'fixe_transport_eur_an': None,
                           'autres_reseau_eur_an': None})
    def calendrier():
        return a_verifier({'annee_mesuree': annee_mesuree, 'sha256_profil': empreinte,
                           'version_grille': 'stcrt-2026-4090-annexe5', 'grille_verifiee': None,
                           'regime': None, 'convention_heure': None,
                           'jours_feries': [], 'jours_feries_exhaustifs': None})
    options = []
    for produit, nom in [('fixe', 'GTV fixe ajusté'), ('cbc', 'CBC V3'), ('tijdsblok', 'Blokstroom'),
                         ('volledig_variabel', 'Reststroom'), ('tijdsduur', 'Tijdsduur')]:
        option = {'id': produit, 'libelle': nom, 'produit': produit,
                  'gtv_fixe_kw': a_verifier(), 'categorie': a_verifier(), 'tarif': tarif(),
                  'calendrier_ponderation': calendrier(),
                  'offre': a_verifier(), 'couts_complementaires_eur_an': a_verifier(),
                  'couts_exhaustifs': a_verifier()}
        if produit != 'fixe':
            option['programme'] = a_verifier()
        if produit == 'cbc':
            option['remuneration'] = a_verifier()
        if produit == 'tijdsblok':
            option['classement_tarifaire'] = a_verifier()
        if produit in ('tijdsblok', 'volledig_variabel', 'tijdsduur'):
            option['gtv_variable_kw'] = a_verifier()
            option['part_variable_facturee'] = a_verifier()
        options.append(option)
    return {'provenance': a_verifier({'nature': None, 'canal': 'afname', 'site_unique': None,
                                     'qualites_controlees': None, 'fuseau_confirme': None, 'sha256_profil': empreinte}),
            'site': a_verifier(),
            'contrat_actuel': a_verifier({'produit': None, 'gtv_kw': None, 'categorie': None}),
            'tarif_actuel': tarif(),
            'calendrier_ponderation_actuel': calendrier(),
            'couts_actuels_eur_an': a_verifier(), 'couts_actuels_exhaustifs': a_verifier(),
            'cout_depassement_actuel_eur_an': a_verifier(),
            'date_comparaison': date.today().isoformat(), 'annee_tarifaire': date.today().year,
            'options': options}
