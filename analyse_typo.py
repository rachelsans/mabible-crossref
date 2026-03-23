#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse_typo.py — Outil d'analyse typographique pour maBible
Analyse les fichiers USX 3.0 et détecte les anomalies typographiques
selon des règles définies par langue et par version.

Usage :
  python analyse_typo.py JHN.usx --version S21
  python analyse_typo.py --dossier ./S21/ --version S21
"""

import argparse
import csv
import html
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Anomalie:
    """Représente une anomalie ou observation typographique détectée."""
    livre: str
    reference: str
    extrait: str
    anomalie: str
    correction: str
    regle_id: str
    contexte: str  # 'texte', 'titre', 'note', 'introduction', 'référence'
    position: int = 0  # position dans le texte pour le surlignage
    type: str = "anomalie"  # 'anomalie' ou 'observation'


# ═══════════════════════════════════════════════════════════════════
# PROFILS DE VERSIONS — Choix éditoriaux (Type B)
# ═══════════════════════════════════════════════════════════════════

# Chaque version définit ses conventions propres.
# Les règles marquées True sont des choix éditoriaux à NE PAS signaler.

PROFILS_VERSIONS = {
    "S21": {
        "langue": "FR",
        "nom": "Louis Segond 21",
        "choix_editoriaux": {
            # Ponctuation double collée (pas d'espace avant ; : ! ?)
            "ponctuation_double_collee": True,
            # Guillemets collés au texte (pas d'espace insécable)
            "guillemets_colles": True,
            # Apostrophe droite U+0027 (pas U+2019)
            "apostrophe_droite": True,
            # Aucune espace insécable (ni U+00A0, ni U+202F)
            "pas_espace_insecable": True,
            # Guillemets de reprise »Mot
            "guillemets_reprise": True,
            # Crochets pour insertions éditoriales
            "crochets_editoriaux": True,
            # Astérisque pour citations bibliques
            "asterisque_citations": True,
            # Combinaison *« avant guillemet
            "asterisque_guillemet": True,
        },
        # Détail des choix éditoriaux Type B pour le rapport
        "choix_editoriaux_detail": [
            {
                "num": 1,
                "convention": "Virgule , (U+002C) / Point . (U+002E)",
                "choix": "Usage standard. Collés au mot, suivis d'une espace.",
                "norme": "Idem",
                "coherence": "100% cohérent",
            },
            {
                "num": 2,
                "convention": "Points de suspension … (U+2026)",
                "choix": "Caractère unique U+2026 (jamais trois points).",
                "norme": "U+2026 exclusivement",
                "coherence": "100% cohérent",
            },
            {
                "num": 3,
                "convention": "Espace avant ; : ! ?",
                "choix": "Aucune espace — signe collé au mot. C'est un choix Type B, différent de la norme française.",
                "norme": "Espace insécable avant (U+00A0 ou U+202F)",
                "coherence": "100% cohérent",
                "type_b": True,
            },
            {
                "num": 4,
                "convention": "Type d'espace insécable",
                "choix": "Non applicable. Aucune espace insécable (U+00A0 ni U+202F) n'est utilisée.",
                "norme": "U+202F avant ; ! ? / U+00A0 avant :",
                "coherence": "N/A — conséquence du choix n°3",
                "type_b": True,
            },
            {
                "num": 5,
                "convention": "Guillemets français « » (U+00AB / U+00BB)",
                "choix": "« collé au mot qui suit, » collé au mot qui précède. Pas d'espace insécable intérieure.",
                "norme": "Espace insécable : « texte »",
                "coherence": "100% cohérent",
                "type_b": True,
            },
            {
                "num": 6,
                "convention": "Guillemets de reprise »",
                "choix": "Le » fermant en début de paragraphe, collé au mot, signale la continuation d'un discours direct.",
                "norme": "Pas de convention standard (usage éditorial)",
                "coherence": "100% cohérent",
                "type_b": True,
            },
            {
                "num": 7,
                "convention": "Guillemets simples \u2018 \u2019 (U+2018 / U+2019)",
                "choix": "Second niveau de citation (citation dans une citation).",
                "norme": "Guillemets simples \u2018 \u2019 ou \" \" anglais",
                "coherence": "Cohérent",
            },
            {
                "num": 8,
                "convention": "Apostrophe",
                "choix": "Apostrophe droite ' (U+0027) pour toutes les élisions. Choix Type B — la norme FR utilise U+2019.",
                "norme": "Apostrophe typographique \u2019 (U+2019)",
                "coherence": "99,98% cohérent (51 095 U+0027 vs 12 U+2019)",
                "type_b": True,
            },
            {
                "num": 9,
                "convention": "Trait d'union - (U+002D)",
                "choix": "Mots composés : peut-être, celui-ci, Jésus-Christ. Toujours collé aux mots.",
                "norme": "Idem",
                "coherence": "Cohérent",
            },
            {
                "num": 10,
                "convention": "Tiret demi-cadratin \u2013 (U+2013)",
                "choix": "Incises narratives (espace \u2013 espace) et plages de références (chiffre\u2013chiffre).",
                "norme": "Demi-cadratin ou cadratin pour les incises",
                "coherence": "100% cohérent",
            },
            {
                "num": 11,
                "convention": "Tiret cadratin \u2014 (U+2014)",
                "choix": "Non utilisé dans la S21. 0 occurrence.",
                "norme": "Usage anglo-saxon ou littéraire",
                "coherence": "100% — absent du corpus",
            },
            {
                "num": 12,
                "convention": "Crochets [ ] (U+005B / U+005D)",
                "choix": "Insertions éditoriales dans le texte : mots ajoutés par les traducteurs, absents de l'original.",
                "norme": "Signalent un ajout éditorial",
                "coherence": "100% cohérent",
                "type_b": True,
            },
            {
                "num": 13,
                "convention": "Parenthèses ( )",
                "choix": "Uniquement dans les notes de bas de page pour les précisions éditoriales.",
                "norme": "Usage standard",
                "coherence": "100% cohérent",
            },
            {
                "num": 14,
                "convention": "Astérisque * (U+002A)",
                "choix": "Signale un passage cité ou repris ailleurs dans les Écritures. Toujours collé au mot qui suit.",
                "norme": "Pas de règle typo standard",
                "coherence": "Cohérent",
                "type_b": True,
            },
            {
                "num": 15,
                "convention": "Espaces",
                "choix": "Un seul type d'espace : U+0020. Aucune insécable U+00A0 ni fine U+202F.",
                "norme": "U+00A0 et U+202F avant ponctuation double et dans guillemets",
                "coherence": "100% cohérent",
                "type_b": True,
            },
        ],
        # Tableau de synthèse des signes typographiques
        "synthese_signes": [
            # (catégorie, nom, signe, code, statut, description, regle_id_lien)
            # statut: "RAS" | "Choix éditorial" | "Anomalie" | "Observation" | "Info"
            ("PONCTUATION SIMPLE", None, None, None, None, None, None),
            (None, "Virgule", ",", "U+002C", "RAS", "Usage standard", None),
            (None, "Point", ".", "U+002E", "RAS", "Usage standard", None),
            (None, "Points de suspension", "\u2026", "U+2026", "Anomalie",
             "… collé au mot suivant sans espace", "R-FR-04"),
            ("PONCTUATION DOUBLE", None, None, None, None, None, None),
            (None, "Point-virgule", ";", "U+003B", "Choix éditorial",
             "Collé au mot (Type B)", None),
            (None, "Deux-points", ":", "U+003A", "Choix éditorial",
             "Collé au mot (Type B)", None),
            (None, "Point d'exclamation", "!", "U+0021", "Choix éditorial",
             "Collé au mot (Type B)", None),
            (None, "Point d'interrogation", "?", "U+003F", "Choix éditorial",
             "Collé au mot (Type B)", None),
            ("GUILLEMETS", None, None, None, None, None, None),
            (None, "Guillemet ouvrant «", "\u00AB", "U+00AB", "Choix éditorial",
             "\u00ABmot \u2014 collé au texte (Type B)", None),
            (None, "Guillemet fermant \u00BB", "\u00BB", "U+00BB", "Choix éditorial",
             "mot\u00BB \u2014 collé au texte (Type B)", None),
            (None, "Guillemet fermant \u00BB (reprise)", "\u00BB", "U+00BB", "Observation",
             "\u00BBMot \u2014 guillemets de reprise (convention S21)", "O-FR-01"),
            (None, "Astérisque + guillemet", "*\u00AB", None, "Observation",
             "*\u00AB : astérisque collé avant guillemet ouvrant", "O-FR-02"),
            (None, "Guillemets simples (2nd niv.)", "\u2018 \u2019", "U+2018/9", "Choix éditorial",
             "Second niveau de citation", None),
            ("APOSTROPHES", None, None, None, None, None, None),
            (None, "Apostrophe droite", "'", "U+0027", "Choix éditorial",
             "Apostrophe droite U+0027 (Type B)", None),
            (None, "Apostrophe typo (anomalie)", "\u2019", "U+2019", "Anomalie",
             "U+2019 utilisée comme apostrophe au lieu de U+0027", "R-FR-08b"),
            (None, "Séparateur de milliers", "\u2019", "U+2019", "Observation",
             "U+2019 comme séparateur de milliers entre chiffres (12\u2019000)", "O-FR-03"),
            ("TIRETS", None, None, None, None, None, None),
            (None, "Trait d'union (incise)", "-", "U+002D", "Anomalie",
             "Trait d'union comme tiret d'incise (espace - espace)", "R-FR-09"),
            (None, "Tiret demi-cadratin (incise)", "\u2013", "U+2013", "Choix éditorial",
             "Incises (espace \u2013 espace) \u2014 convention S21", None),
            (None, "Tiret demi-cadratin (plages)", "\u2013", "U+2013", "Info",
             "Plages de références (chiffre\u2013chiffre)", None),
            (None, "Tiret cadratin", "\u2014", "U+2014", "RAS",
             "0 occurrence", None),
            ("PARENTHÈSES / CROCHETS", None, None, None, None, None, None),
            (None, "Crochets [ ]", "[]", "U+005B/D", "Choix éditorial",
             "Insertions éditoriales entre crochets (convention S21)", None),
            ("CARACTÈRES SPÉCIAUX", None, None, None, None, None, None),
            (None, "Astérisque", "*", "U+002A", "Choix éditorial",
             "Passages cités dans les Écritures", None),
            ("ESPACES", None, None, None, None, None, None),
            (None, "Espace normale", " ", "U+0020", "Info",
             "Seul type d'espace utilisé", None),
            (None, "Espace insécable", " ", "U+00A0", "Choix éditorial",
             "0 occurrence \u2014 non utilisée (conséquence du Type B)", None),
            (None, "Espace fine insécable", " ", "U+202F", "Choix éditorial",
             "0 occurrence \u2014 non utilisée (conséquence du Type B)", None),
        ],
    },
    # Profils extensibles pour d'autres versions
    "LSG": {
        "langue": "FR",
        "nom": "Louis Segond 1910",
        "choix_editoriaux": {},
        "choix_editoriaux_detail": [],
        "synthese_signes": [],
    },
    "NBS": {
        "langue": "FR",
        "nom": "Nouvelle Bible Segond",
        "choix_editoriaux": {},
        "choix_editoriaux_detail": [],
        "synthese_signes": [],
    },
    "NIV": {
        "langue": "EN",
        "nom": "New International Version",
        "choix_editoriaux": {},
        "choix_editoriaux_detail": [],
        "synthese_signes": [],
    },
    "RVR": {
        "langue": "ES",
        "nom": "Reina Valera Revisada",
        "choix_editoriaux": {},
        "choix_editoriaux_detail": [],
        "synthese_signes": [],
    },
}


# ═══════════════════════════════════════════════════════════════════
# RÈGLES TYPOGRAPHIQUES PAR LANGUE
# ═══════════════════════════════════════════════════════════════════

def get_regles(langue: str, choix_editoriaux: dict) -> list:
    """Retourne la liste des règles applicables pour une langue,
    en excluant celles couvertes par les choix éditoriaux de la version."""

    regles = []

    if langue == "FR":
        regles = _regles_fr(choix_editoriaux)
    elif langue == "EN":
        regles = _regles_en(choix_editoriaux)
    elif langue == "ES":
        regles = _regles_es(choix_editoriaux)
    else:
        print(f"Langue non supportée : {langue}", file=sys.stderr)
        sys.exit(1)

    return regles


def _regles_fr(ce: dict) -> list:
    """Règles typographiques françaises, filtrées par choix éditoriaux."""
    regles = []

    # ── PONCTUATION SIMPLE ──

    # Virgule : pas d'espace avant, espace après
    regles.append({
        "id": "R-FR-01",
        "nom": "Espace avant virgule",
        "pattern": re.compile(r'\S\s,'),
        "description": "Espace avant la virgule",
        "correction": "Supprimer l'espace avant la virgule",
    })

    # Point : pas d'espace avant
    regles.append({
        "id": "R-FR-02",
        "nom": "Espace avant point",
        "pattern": re.compile(r'\S\s\.(?!\.)'),  # exclure les ...
        "description": "Espace avant le point",
        "correction": "Supprimer l'espace avant le point",
    })

    # Points de suspension : toujours U+2026, jamais trois points
    # Détecte ... (collés) et . . . (espacés)
    regles.append({
        "id": "R-FR-03a",
        "nom": "Triple point collé au lieu de …",
        "pattern": re.compile(r'\.{3}'),
        "description": "Trois points consécutifs ... au lieu du caractère … (U+2026)",
        "correction": "Remplacer ... par … (U+2026)",
    })
    regles.append({
        "id": "R-FR-03b",
        "nom": "Triple point espacé au lieu de …",
        "pattern": re.compile(r'\. \. \.'),
        "description": "Trois points espacés . . . au lieu du caractère … (U+2026)",
        "correction": "Remplacer . . . par … (U+2026)",
    })

    # Points de suspension collés au mot suivant (pas d'espace après)
    regles.append({
        "id": "R-FR-04",
        "nom": "Points de suspension collés au mot suivant",
        "pattern": re.compile(r'…[A-ZÀ-Ža-zà-ž]'),
        "description": "Points de suspension … collés au mot suivant sans espace",
        "correction": "Ajouter une espace après …",
    })

    # ── PONCTUATION DOUBLE ──
    if not ce.get("ponctuation_double_collee"):
        # Espace insécable avant ; : ! ?
        for signe, nom in [
            (';', 'point-virgule'),
            (':', 'deux-points'),
            ('!', "point d'exclamation"),
            ('?', "point d'interrogation"),
        ]:
            escaped = re.escape(signe)
            regles.append({
                "id": f"R-FR-05-{signe}",
                "nom": f"Espace avant {nom}",
                "pattern": re.compile(rf'[^\s]{escaped}'),
                "description": f"Pas d'espace (insécable) avant {nom} {signe}",
                "correction": f"Ajouter une espace insécable avant {signe}",
            })

    # ── GUILLEMETS ──
    if not ce.get("guillemets_colles"):
        # « doit être suivi d'une espace insécable
        regles.append({
            "id": "R-FR-06",
            "nom": "Espace après «",
            "pattern": re.compile(r'«[^\s\u00A0\u202F]'),
            "description": "Pas d'espace insécable après le guillemet ouvrant «",
            "correction": "Ajouter une espace insécable après «",
        })
        # » doit être précédé d'une espace insécable
        regles.append({
            "id": "R-FR-07",
            "nom": "Espace avant »",
            "pattern": re.compile(r'[^\s\u00A0\u202F]»'),
            "description": "Pas d'espace insécable avant le guillemet fermant »",
            "correction": "Ajouter une espace insécable avant »",
        })

    # ── APOSTROPHE ──
    if not ce.get("apostrophe_droite"):
        # Apostrophe droite U+0027 doit être remplacée par U+2019
        regles.append({
            "id": "R-FR-08",
            "nom": "Apostrophe droite",
            "pattern": re.compile(r"(?<=[a-zA-ZÀ-ÿœŒæÆ])'(?=[a-zA-ZÀ-ÿœŒæÆ])"),
            "description": "Apostrophe droite U+0027 au lieu de typographique U+2019",
            "correction": "Remplacer ' (U+0027) par \u2019 (U+2019)",
        })
    else:
        # Si la version utilise U+0027, détecter les U+2019 résiduels comme apostrophe
        regles.append({
            "id": "R-FR-08b",
            "nom": "Apostrophe typographique résiduelle",
            "pattern": re.compile(r"(?<=[a-zA-ZÀ-ÿœŒæÆ])\u2019(?=[a-zA-ZÀ-ÿœŒæÆ])"),
            "description": "Apostrophe typographique U+2019 utilisée au lieu de U+0027 (convention de la version)",
            "correction": "Remplacer \u2019 (U+2019) par ' (U+0027) pour cohérence",
        })

    # ── TIRETS ──
    # Trait d'union utilisé comme tiret d'incise (espace - espace)
    regles.append({
        "id": "R-FR-09",
        "nom": "Trait d'union comme tiret d'incise",
        "pattern": re.compile(r'(?<=\S) - (?=\S)|(?<=\S) -$|^- (?=\S)', re.MULTILINE),
        "description": "Trait d'union - (U+002D) utilisé comme tiret d'incise au lieu de – (U+2013)",
        "correction": "Remplacer - par – (tiret demi-cadratin U+2013)",
    })

    # ── ESPACES MULTIPLES ──
    regles.append({
        "id": "R-FR-10",
        "nom": "Espaces multiples",
        "pattern": re.compile(r'[^\S\n]{2,}'),
        "description": "Plusieurs espaces consécutives",
        "correction": "Réduire à une seule espace",
        "exclure_contexte": "note",  # les notes ont parfois un formatage spécial
    })

    # ── OBSERVATIONS (cas notables, ni anomalies ni choix éditoriaux) ──

    # Guillemets de reprise »Mot (continuation de discours direct)
    if ce.get("guillemets_reprise"):
        regles.append({
            "id": "O-FR-01",
            "nom": "Guillemet de reprise »Mot",
            "pattern": re.compile(r'»[A-ZÀ-ÿœŒ]'),
            "description": "Guillemet de reprise » collé au mot — continuation de discours direct",
            "correction": "Convention S21 : pas de correction nécessaire",
            "type": "observation",
        })

    # Astérisque collé avant guillemet ouvrant *«
    if ce.get("asterisque_guillemet"):
        regles.append({
            "id": "O-FR-02",
            "nom": "Combinaison *« (astérisque + guillemet)",
            "pattern": re.compile(r'\*«'),
            "description": "Astérisque collé avant guillemet ouvrant *« — passage biblique cité",
            "correction": "Convention S21 : pas de correction nécessaire",
            "type": "observation",
        })

    # Séparateur de milliers U+2019 entre chiffres (ex. 12'000)
    if ce.get("apostrophe_droite"):
        regles.append({
            "id": "O-FR-03",
            "nom": "Séparateur de milliers U+2019",
            "pattern": re.compile(r'\d\u2019\d{3}'),
            "description": "U+2019 utilisé comme séparateur de milliers entre chiffres",
            "correction": "À vérifier : usage courant en Suisse romande",
            "type": "observation",
        })

    return regles


def _regles_en(ce: dict) -> list:
    """Règles typographiques anglaises."""
    regles = []

    # En anglais : ponctuation collée au mot (pas d'espace avant , . ; : ! ?)
    for signe, nom in [
        (',', 'comma'), ('.', 'period'), (';', 'semicolon'),
        (':', 'colon'), ('!', 'exclamation'), ('?', 'question mark'),
    ]:
        escaped = re.escape(signe)
        regles.append({
            "id": f"R-EN-01-{signe}",
            "nom": f"Space before {nom}",
            "pattern": re.compile(rf'\s{escaped}'),
            "description": f"Space before {nom} {signe}",
            "correction": f"Remove space before {signe}",
        })

    # Triple dots instead of ellipsis character
    regles.append({
        "id": "R-EN-02",
        "nom": "Triple dots instead of ellipsis",
        "pattern": re.compile(r'\.{3}'),
        "description": "Three dots instead of ellipsis character … (U+2026)",
        "correction": "Replace ... with … (U+2026)",
    })

    # Multiple spaces
    regles.append({
        "id": "R-EN-03",
        "nom": "Multiple spaces",
        "pattern": re.compile(r'[^\S\n]{2,}'),
        "description": "Multiple consecutive spaces",
        "correction": "Reduce to single space",
    })

    return regles


def _regles_es(ce: dict) -> list:
    """Règles typographiques espagnoles."""
    regles = []

    # En espagnol : ponctuation collée au mot
    for signe, nom in [
        (',', 'coma'), ('.', 'punto'), (';', 'punto y coma'),
        (':', 'dos puntos'), ('!', 'exclamación'), ('?', 'interrogación'),
    ]:
        escaped = re.escape(signe)
        regles.append({
            "id": f"R-ES-01-{signe}",
            "nom": f"Espacio antes de {nom}",
            "pattern": re.compile(rf'\s{escaped}'),
            "description": f"Espacio antes de {nom} {signe}",
            "correction": f"Eliminar espacio antes de {signe}",
        })

    # Signos de apertura ¿ ¡
    regles.append({
        "id": "R-ES-02",
        "nom": "Signo de apertura ¿",
        "pattern": re.compile(r'\?[^¡¿\s]'),
        "description": "Falta signo de apertura ¿",
        "correction": "Verificar si falta ¿ al inicio de la pregunta",
    })

    # Triple dots
    regles.append({
        "id": "R-ES-03",
        "nom": "Triple punto en vez de …",
        "pattern": re.compile(r'\.{3}'),
        "description": "Tres puntos en vez del carácter … (U+2026)",
        "correction": "Reemplazar ... por … (U+2026)",
    })

    return regles


# ═══════════════════════════════════════════════════════════════════
# PARSEUR USX 3.0
# ═══════════════════════════════════════════════════════════════════

@dataclass
class VerseText:
    """Texte d'un verset avec sa référence et son type de contenu."""
    livre: str
    chapitre: str
    verset: str
    texte: str
    contexte: str  # 'texte', 'titre', 'note', 'introduction', 'référence'

    @property
    def reference(self) -> str:
        return f"{self.livre} {self.chapitre}:{self.verset}"


# Classification des styles USX <para> en types de contenu
_STYLE_CONTEXTE = {
    # Texte biblique courant
    'p': 'texte', 'nb': 'texte', 'm': 'texte', 'mi': 'texte',
    'q': 'texte', 'q1': 'texte', 'q2': 'texte', 'q3': 'texte',
    'qr': 'texte', 'qc': 'texte', 'qm': 'texte', 'qm1': 'texte', 'qm2': 'texte',
    'b': 'texte',
    'pi': 'texte', 'pi1': 'texte', 'pi2': 'texte',
    'li': 'texte', 'li1': 'texte', 'li2': 'texte',
    'pc': 'texte', 'cls': 'texte', 'pm': 'texte', 'pmo': 'texte', 'pmc': 'texte',
    # Titres et péricopes
    's': 'titre', 's1': 'titre', 's2': 'titre', 's3': 'titre',
    'ms': 'titre', 'ms1': 'titre', 'ms2': 'titre',
    'mt': 'titre', 'mt1': 'titre', 'mt2': 'titre', 'mt3': 'titre',
    'mte': 'titre', 'mte1': 'titre', 'mte2': 'titre',
    'd': 'titre', 'sp': 'titre',
    # Références de section
    'r': 'référence', 'mr': 'référence', 'sr': 'référence',
    # Introductions
    'ip': 'introduction', 'ipi': 'introduction', 'im': 'introduction',
    'is': 'introduction', 'is1': 'introduction', 'is2': 'introduction',
    'imi': 'introduction', 'imq': 'introduction', 'ipr': 'introduction',
    'iq': 'introduction', 'iq1': 'introduction', 'iq2': 'introduction',
    'iot': 'introduction', 'io': 'introduction', 'io1': 'introduction',
    'io2': 'introduction', 'iex': 'introduction',
}

# Styles de métadonnées à ignorer (pas du contenu à analyser)
_STYLES_IGNORES = {'id', 'ide', 'h', 'toc1', 'toc2', 'toc3', 'rem'}


def parse_usx(filepath: str) -> list[VerseText]:
    """Parse un fichier USX 3.0 et retourne une liste de VerseText.

    Parcours exhaustif de TOUS les noeuds de texte du fichier :
    - Texte biblique courant (p, q, nb, m, li…)
    - Titres de péricopes (s, ms, d, sp…)
    - Notes de bas de page (note)
    - Introductions (ip, is, io…)
    - Références de section (r, mr, sr)

    Les styles de métadonnées (h, toc*, rem, id) sont les seuls exclus.
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Déterminer le code du livre
    book_elem = root.find('.//book')
    livre = book_elem.attrib.get('code', 'UNK') if book_elem is not None else 'UNK'

    versets: list[VerseText] = []
    current_chapter = "0"
    current_verse = "0"
    current_contexte = "texte"

    def _extract_all_text(elem) -> str:
        """Extrait récursivement tout le texte d'un élément (hors notes)."""
        parts = []
        if elem.text:
            parts.append(elem.text)
        for child in elem:
            if child.tag == 'note':
                pass  # notes traitées séparément
            else:
                parts.append(_extract_all_text(child))
            if child.tail:
                parts.append(child.tail)
        return ''.join(parts)

    def _extract_note_text(note_elem) -> str:
        """Extrait le texte d'une note, en incluant le contenu des <ref>."""
        parts = []
        if note_elem.text:
            parts.append(note_elem.text)
        for child in note_elem:
            if child.tag == 'char':
                style = child.attrib.get('style', '')
                # Ignorer les références de note (fr = note reference)
                if style == 'fr':
                    pass
                else:
                    parts.append(_extract_all_text(child))
            elif child.tag == 'ref':
                if child.text:
                    parts.append(child.text)
            else:
                parts.append(_extract_all_text(child))
            if child.tail:
                parts.append(child.tail)
        return ''.join(parts)

    text_buffer: list[str] = []

    def flush_buffer():
        """Sauvegarde le texte accumulé comme un VerseText."""
        nonlocal text_buffer
        if text_buffer:
            combined = ''.join(text_buffer).strip()
            if combined:
                versets.append(VerseText(
                    livre=livre,
                    chapitre=current_chapter,
                    verset=current_verse,
                    texte=combined,
                    contexte=current_contexte,
                ))
            text_buffer = []

    def process_element(elem):
        """Traite un élément et ses enfants, en suivant chapitre/verset."""
        nonlocal current_chapter, current_verse, current_contexte, text_buffer

        if elem.tag == 'chapter' and 'number' in elem.attrib:
            flush_buffer()
            current_chapter = elem.attrib['number']
            return

        if elem.tag == 'verse':
            if 'sid' in elem.attrib:
                flush_buffer()
                current_verse = elem.attrib.get('number', '0')
            return

        if elem.tag == 'note':
            note_text = _extract_note_text(elem).strip()
            if note_text:
                versets.append(VerseText(
                    livre=livre,
                    chapitre=current_chapter,
                    verset=current_verse,
                    texte=note_text,
                    contexte='note',
                ))
            return

        if elem.tag == 'para':
            style = elem.attrib.get('style', '')
            # Ignorer les métadonnées
            if style in _STYLES_IGNORES:
                return
            # Déterminer le contexte à partir du style
            # Les styles non mappés sont traités comme 'texte' par défaut
            flush_buffer()
            current_contexte = _STYLE_CONTEXTE.get(style, 'texte')

        if elem.tag == 'char':
            text_buffer.append(_extract_all_text(elem))
            return

        if elem.tag == 'ref':
            if elem.text:
                text_buffer.append(elem.text)
            return

        # Pour les éléments conteneurs (usx, para, etc.),
        # traiter le texte direct et les enfants
        if elem.text:
            text_buffer.append(elem.text)

        for child in elem:
            process_element(child)
            if child.tail:
                text_buffer.append(child.tail)

        # Flush à la fin de chaque paragraphe
        if elem.tag == 'para':
            flush_buffer()

    process_element(root)
    flush_buffer()

    return versets


# ═══════════════════════════════════════════════════════════════════
# MOTEUR D'ANALYSE
# ═══════════════════════════════════════════════════════════════════

def analyser_fichier(filepath: str, version: str) -> list[Anomalie]:
    """Analyse un fichier USX et retourne les anomalies détectées."""
    profil = PROFILS_VERSIONS.get(version)
    if not profil:
        print(f"Version inconnue : {version}. Versions disponibles : {', '.join(PROFILS_VERSIONS.keys())}", file=sys.stderr)
        sys.exit(1)

    regles = get_regles(profil["langue"], profil["choix_editoriaux"])
    versets = parse_usx(filepath)
    anomalies: list[Anomalie] = []

    for verset in versets:
        for regle in regles:
            # Vérifier l'exclusion de contexte
            if regle.get("exclure_contexte") == verset.contexte:
                continue

            for match in regle["pattern"].finditer(verset.texte):
                # Extraire un extrait de contexte autour du match
                start = max(0, match.start() - 25)
                end = min(len(verset.texte), match.end() + 25)
                extrait = verset.texte[start:end]
                if start > 0:
                    extrait = "…" + extrait
                if end < len(verset.texte):
                    extrait = extrait + "…"

                anomalies.append(Anomalie(
                    livre=verset.livre,
                    reference=verset.reference,
                    extrait=extrait,
                    anomalie=regle["description"],
                    correction=regle["correction"],
                    regle_id=regle["id"],
                    contexte=verset.contexte,
                    position=match.start(),
                    type=regle.get("type", "anomalie"),
                ))

    return anomalies


def analyser_dossier(dossier: str, version: str) -> list[Anomalie]:
    """Analyse tous les fichiers USX/XML d'un dossier."""
    toutes_anomalies: list[Anomalie] = []
    extensions = ('.usx', '.xml')

    fichiers = sorted([
        f for f in Path(dossier).iterdir()
        if f.suffix.lower() in extensions
    ])

    if not fichiers:
        print(f"Aucun fichier USX/XML trouvé dans {dossier}", file=sys.stderr)
        sys.exit(1)

    for fichier in fichiers:
        print(f"  Analyse de {fichier.name}…", file=sys.stderr)
        anomalies = analyser_fichier(str(fichier), version)
        toutes_anomalies.extend(anomalies)

    return toutes_anomalies


# ═══════════════════════════════════════════════════════════════════
# GÉNÉRATION DE RAPPORTS
# ═══════════════════════════════════════════════════════════════════

def generer_csv(anomalies: list[Anomalie], filepath: str):
    """Génère un rapport CSV."""
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            'Livre', 'Référence', 'Contexte', 'Règle',
            'Anomalie', 'Correction suggérée', 'Extrait'
        ])
        for a in anomalies:
            writer.writerow([
                a.livre, a.reference, a.contexte, a.regle_id,
                a.anomalie, a.correction, a.extrait
            ])
    print(f"Rapport CSV généré : {filepath}", file=sys.stderr)


def _highlight_extrait(extrait: str, regle_id: str) -> str:
    """Surligne la partie problématique dans l'extrait avec <mark>.

    Le surlignage est appliqué AVANT l'échappement HTML sur le texte brut,
    puis les parties hors <mark> sont échappées individuellement.
    """

    # Patterns de surlignage selon la règle (appliqués sur le texte brut)
    highlights = {
        "R-FR-01": (r'(\S)(\s,)', 1),
        "R-FR-02": (r'(\S)(\s\.)(?!\.)', 1),
        "R-FR-03": (r'(\.{3})', 0),
        "R-FR-03a": (r'(\.{3})', 0),
        "R-FR-03b": (r'(\. \. \.)', 0),
        "R-FR-04": (r'(\u2026[A-Z\u00C0-\u017Ea-z\u00E0-\u017E])', 0),
        "R-FR-08b": (r'([a-zA-Z\u00C0-\u00FF\u0153\u0152\u00E6\u00C6]\u2019[a-zA-Z\u00C0-\u00FF\u0153\u0152\u00E6\u00C6])', 0),
        "R-FR-09": (r'( - (?=\S)| -$|^- )', 0),
        "R-FR-10": (r'([^\S\n]{2,})', 0),
        "O-FR-01": (r'(\u00BB[A-Z\u00C0-\u00FF\u0153\u0152])', 0),
        "O-FR-02": (r'(\*\u00AB)', 0),
        "O-FR-03": (r'(\d\u2019\d{3})', 0),
    }

    if regle_id not in highlights:
        return html.escape(extrait)

    pattern_str, mark_group = highlights[regle_id]
    m = re.search(pattern_str, extrait, re.MULTILINE)
    if not m:
        return html.escape(extrait)

    # Identifier la portion à surligner
    mark_start = m.start(mark_group)
    mark_end = m.end(mark_group)

    before = html.escape(extrait[:mark_start])
    marked = html.escape(extrait[mark_start:mark_end])
    after = html.escape(extrait[mark_end:])

    return f"{before}<mark>{marked}</mark>{after}"


def generer_html(anomalies: list[Anomalie], filepath: str, version: str):
    """Génère un rapport HTML complet avec :
    1. Tableau de synthèse (RAS / Choix éditorial / Anomalie)
    2. Choix éditoriaux Type B
    3. Anomalies détaillées avec surlignage en contexte
    4. Observations (cas notables, ni anomalies ni choix éditoriaux)
    """
    profil = PROFILS_VERSIONS.get(version, {})
    nom_version = profil.get("nom", version)
    choix_detail = profil.get("choix_editoriaux_detail", [])
    synthese = profil.get("synthese_signes", [])

    # Séparer anomalies et observations
    vraies_anomalies = [a for a in anomalies if a.type == "anomalie"]
    observations = [a for a in anomalies if a.type == "observation"]

    # Regrouper anomalies par règle (sans les observations)
    par_regle: dict[str, list[Anomalie]] = {}
    for a in vraies_anomalies:
        key = f"{a.regle_id} — {a.anomalie}"
        par_regle.setdefault(key, []).append(a)

    # Regrouper observations par règle
    par_obs: dict[str, list[Anomalie]] = {}
    for a in observations:
        key = f"{a.regle_id} — {a.anomalie}"
        par_obs.setdefault(key, []).append(a)

    # Compter par livre (anomalies seulement)
    par_livre: dict[str, int] = {}
    for a in vraies_anomalies:
        par_livre[a.livre] = par_livre.get(a.livre, 0) + 1

    # Compter par regle_id pour la synthèse (anomalies + observations)
    count_par_regle_id: dict[str, int] = {}
    for a in anomalies:
        count_par_regle_id[a.regle_id] = count_par_regle_id.get(a.regle_id, 0) + 1

    nb_choix_b = sum(1 for c in choix_detail if c.get("type_b"))

    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rapport typographique — {html.escape(nom_version)}</title>
<style>
  :root {{
    --bg: #fafaf9;
    --card: #ffffff;
    --border: #e7e5e4;
    --text: #1c1917;
    --muted: #78716c;
    --accent: #dc2626;
    --accent-bg: #fef2f2;
    --accent-border: #fecaca;
    --blue: #2563eb;
    --blue-bg: #eff6ff;
    --green: #16a34a;
    --green-bg: #f0fdf4;
    --green-border: #bbf7d0;
    --amber: #d97706;
    --amber-bg: #fffbeb;
    --amber-border: #fde68a;
    --slate: #64748b;
    --slate-bg: #f8fafc;
    --slate-border: #e2e8f0;
    --purple: #7c3aed;
    --purple-bg: #f5f3ff;
    --purple-border: #ddd6fe;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1300px;
    margin: 0 auto;
  }}
  h1 {{ font-size: 1.75rem; margin-bottom: 0.25rem; }}
  h2 {{ font-size: 1.2rem; margin-bottom: 0.5rem; }}
  h3 {{ font-size: 1.05rem; margin-bottom: 0.5rem; color: var(--text); }}
  .subtitle {{
    color: var(--muted);
    margin-bottom: 2rem;
    font-size: 0.95rem;
  }}
  .stats {{
    display: flex;
    gap: 1rem;
    margin-bottom: 2rem;
    flex-wrap: wrap;
  }}
  .stat-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem 1.5rem;
    min-width: 150px;
  }}
  .stat-card .number {{
    font-size: 2rem;
    font-weight: 700;
    color: var(--accent);
  }}
  .stat-card .label {{
    font-size: 0.85rem;
    color: var(--muted);
  }}
  .stat-card.ok .number {{ color: var(--green); }}
  .stat-card.info .number {{ color: var(--blue); }}

  /* Navigation par onglets */
  .nav-tabs {{
    display: flex;
    gap: 0;
    margin-bottom: 0;
    border-bottom: 2px solid var(--border);
  }}
  .nav-tab {{
    padding: 0.75rem 1.5rem;
    cursor: pointer;
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--muted);
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    transition: all 0.15s;
    user-select: none;
  }}
  .nav-tab:hover {{ color: var(--text); }}
  .nav-tab.active {{
    color: var(--blue);
    border-bottom-color: var(--blue);
  }}
  .tab-content {{
    display: none;
    padding-top: 1.5rem;
  }}
  .tab-content.active {{ display: block; }}

  /* Sections */
  .section {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 1.5rem;
    overflow: hidden;
  }}
  .section-header {{
    padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .section-header h3 {{
    font-size: 1rem;
    font-weight: 600;
    margin: 0;
  }}

  /* Badges */
  .badge {{
    display: inline-block;
    border-radius: 999px;
    padding: 0.15rem 0.75rem;
    font-size: 0.8rem;
    font-weight: 600;
    white-space: nowrap;
  }}
  .badge-anomalie {{
    background: var(--accent-bg);
    color: var(--accent);
    border: 1px solid var(--accent-border);
  }}
  .badge-choix {{
    background: var(--green-bg);
    color: var(--green);
    border: 1px solid var(--green-border);
  }}
  .badge-ras {{
    background: var(--slate-bg);
    color: var(--slate);
    border: 1px solid var(--slate-border);
  }}
  .badge-obs {{
    background: var(--amber-bg);
    color: var(--amber);
    border: 1px solid var(--amber-border);
  }}
  .badge-info {{
    background: var(--purple-bg);
    color: var(--purple);
    border: 1px solid var(--purple-border);
  }}
  .badge-type-b {{
    background: var(--blue-bg);
    color: var(--blue);
    border: 1px solid #bfdbfe;
    font-size: 0.7rem;
    padding: 0.1rem 0.5rem;
    margin-left: 0.5rem;
  }}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }}
  th {{
    text-align: left;
    padding: 0.6rem 1rem;
    background: #f5f5f4;
    font-weight: 600;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
  }}
  td {{
    padding: 0.6rem 1rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tr:last-child td {{ border-bottom: none; }}
  tr.cat-row td {{
    background: #f8fafc;
    font-weight: 700;
    font-size: 0.85rem;
    color: var(--slate);
    letter-spacing: 0.03em;
    padding-top: 0.8rem;
  }}
  .ref {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.85rem;
    color: var(--blue);
    white-space: nowrap;
  }}
  .ctx {{
    font-size: 0.7rem;
    text-transform: uppercase;
    font-weight: 600;
    letter-spacing: 0.03em;
    white-space: nowrap;
  }}
  .ctx-texte {{ color: var(--text); }}
  .ctx-titre {{ color: var(--purple); }}
  .ctx-note {{ color: var(--amber); }}
  .ctx-introduction {{ color: var(--green); }}
  .ctx-référence {{ color: var(--slate); }}
  .extrait {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.85rem;
    background: #f5f5f4;
    padding: 0.3rem 0.5rem;
    border-radius: 4px;
    white-space: pre-wrap;
    word-break: break-word;
    display: inline-block;
  }}
  mark {{
    background: #fde047;
    color: #1c1917;
    padding: 0.1rem 0.2rem;
    border-radius: 2px;
    font-weight: 600;
  }}
  .choix-table td {{ font-size: 0.85rem; }}
  .choix-table .col-num {{ width: 3rem; text-align: center; color: var(--muted); }}
  .choix-table .col-conv {{ width: 22%; }}
  .choix-table .col-choix {{ width: 32%; }}
  .choix-table .col-norme {{ width: 22%; color: var(--muted); }}
  .choix-table .col-coh {{ width: 14%; }}
  .note-text {{
    font-size: 0.85rem;
    color: var(--muted);
    padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--border);
    line-height: 1.5;
  }}
  footer {{
    text-align: center;
    color: var(--muted);
    font-size: 0.8rem;
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
  }}
</style>
</head>
<body>

<h1>Rapport typographique — {html.escape(nom_version)}</h1>
<p class="subtitle">Analyse automatique des fichiers USX 3.0 — maBible.app</p>

<!-- ═══ STATISTIQUES ═══ -->
<div class="stats">
  <div class="stat-card">
    <div class="number">{len(vraies_anomalies)}</div>
    <div class="label">anomalies détectées</div>
  </div>
  <div class="stat-card ok">
    <div class="number">{nb_choix_b}</div>
    <div class="label">choix éditoriaux (Type B)</div>
  </div>
  <div class="stat-card" style="--accent:#d97706">
    <div class="number" style="color:var(--amber)">{len(observations)}</div>
    <div class="label">observations</div>
  </div>
  <div class="stat-card info">
    <div class="number">{len(par_livre)}</div>
    <div class="label">livres concernés</div>
  </div>
</div>

<!-- ═══ ONGLETS ═══ -->
<div class="nav-tabs">
  <div class="nav-tab active" onclick="showTab('tab-synthese')">Synthèse</div>
  <div class="nav-tab" onclick="showTab('tab-choix')">Choix éditoriaux</div>
  <div class="nav-tab" onclick="showTab('tab-anomalies')">Anomalies ({len(vraies_anomalies)})</div>
  <div class="nav-tab" onclick="showTab('tab-observations')">Observations ({len(observations)})</div>
</div>
"""

    # ═══════════════════════════════════════════════════════
    # ONGLET 1 — SYNTHÈSE
    # ═══════════════════════════════════════════════════════
    html_content += """
<div id="tab-synthese" class="tab-content active">
<h2>Tableau de synthèse des signes typographiques</h2>
<p style="color: #78716c; font-size: 0.9rem; margin-bottom: 1rem;">
  Vue d'ensemble de chaque signe analysé avec son statut :
  <span class="badge badge-ras">RAS</span>
  <span class="badge badge-choix">Choix éditorial</span>
  <span class="badge badge-anomalie">Anomalie</span>
  <span class="badge badge-obs">Observation</span>
  <span class="badge badge-info">Info</span>
</p>
"""

    if synthese:
        html_content += """
<div class="section">
<div class="section-body">
<table>
  <thead>
    <tr>
      <th>Nom</th>
      <th>Signe</th>
      <th>Code</th>
      <th>Statut</th>
      <th>Description</th>
      <th>Nb trouvé</th>
    </tr>
  </thead>
  <tbody>
"""
        for row in synthese:
            cat, nom, signe, code, statut, desc, regle_lien = row
            if cat is not None:
                # Ligne de catégorie
                html_content += f'    <tr class="cat-row"><td colspan="6">{html.escape(cat)}</td></tr>\n'
            else:
                # Badge de statut
                badge_cls = {
                    "RAS": "badge-ras",
                    "Choix éditorial": "badge-choix",
                    "Anomalie": "badge-anomalie",
                    "Observation": "badge-obs",
                    "Info": "badge-info",
                }.get(statut, "badge-ras")

                # Nombre trouvé dans l'analyse
                nb = ""
                if regle_lien and regle_lien in count_par_regle_id:
                    nb = f'<strong style="color: var(--accent)">{count_par_regle_id[regle_lien]}</strong>'

                # Lien vers la section détaillée (anomalie ou observation)
                nom_display = html.escape(nom or "")
                if regle_lien and regle_lien in count_par_regle_id:
                    if regle_lien.startswith("O-"):
                        nom_display = f'<a href="#obs-{regle_lien}" style="color:var(--amber);text-decoration:none;font-weight:600">{nom_display}</a>'
                        nb = f'<strong style="color: var(--amber)">{count_par_regle_id[regle_lien]}</strong>'
                    else:
                        nom_display = f'<a href="#detail-{regle_lien}" style="color:var(--accent);text-decoration:none;font-weight:600">{nom_display}</a>'

                html_content += f"""    <tr>
      <td>{nom_display}</td>
      <td style="font-family:monospace;font-size:0.95rem">{html.escape(signe or "")}</td>
      <td style="font-family:monospace;font-size:0.8rem;color:var(--muted)">{html.escape(code or "")}</td>
      <td><span class="badge {badge_cls}">{html.escape(statut or "")}</span></td>
      <td style="font-size:0.85rem">{html.escape(desc or "")}</td>
      <td style="text-align:center">{nb}</td>
    </tr>
"""

        html_content += """  </tbody>
</table>
</div>
</div>
"""
    else:
        html_content += '<p style="color:var(--muted);font-style:italic">Pas de tableau de synthèse disponible pour cette version.</p>\n'

    html_content += "</div>\n"

    # ═══════════════════════════════════════════════════════
    # ONGLET 2 — CHOIX ÉDITORIAUX
    # ═══════════════════════════════════════════════════════
    html_content += f"""
<div id="tab-choix" class="tab-content">
<h2>Choix éditoriaux typographiques — {html.escape(nom_version)}</h2>
<p style="color: #78716c; font-size: 0.9rem; margin-bottom: 1rem;">
  Conventions propres à la version. Les choix marqués <span class="badge badge-type-b">Type B</span>
  diffèrent de la norme typographique française standard mais sont cohérents dans la version.
  Ils sont <strong>exclus de la détection d'anomalies</strong>.
</p>
"""

    if choix_detail:
        html_content += """
<div class="section">
<div class="section-body">
<table class="choix-table">
  <thead>
    <tr>
      <th class="col-num">N°</th>
      <th class="col-conv">Convention</th>
      <th class="col-choix">Choix de la version</th>
      <th class="col-norme">Norme FR standard</th>
      <th class="col-coh">Cohérence</th>
    </tr>
  </thead>
  <tbody>
"""
        for c in choix_detail:
            type_b_badge = ' <span class="badge badge-type-b">Type B</span>' if c.get("type_b") else ""
            html_content += f"""    <tr>
      <td class="col-num">{c['num']}</td>
      <td class="col-conv">{html.escape(c['convention'])}{type_b_badge}</td>
      <td class="col-choix">{html.escape(c['choix'])}</td>
      <td class="col-norme">{html.escape(c['norme'])}</td>
      <td class="col-coh">{html.escape(c['coherence'])}</td>
    </tr>
"""
        html_content += """  </tbody>
</table>
</div>
</div>
"""
    else:
        html_content += '<p style="color:var(--muted);font-style:italic">Pas de choix éditoriaux détaillés pour cette version.</p>\n'

    html_content += "</div>\n"

    # ═══════════════════════════════════════════════════════
    # ONGLET 3 — ANOMALIES DÉTAILLÉES
    # ═══════════════════════════════════════════════════════
    html_content += """
<div id="tab-anomalies" class="tab-content">
<h2>Anomalies détaillées</h2>
<p style="color: #78716c; font-size: 0.9rem; margin-bottom: 1rem;">
  Chaque anomalie est affichée avec sa référence biblique et un extrait
  de contexte où la partie problématique est <mark>surlignée</mark>.
</p>
"""

    if not vraies_anomalies:
        html_content += '<p style="color:var(--green);font-weight:600;font-size:1.1rem;padding:2rem 0">Aucune anomalie détectée.</p>\n'
    else:
        for i, (key, items) in enumerate(sorted(par_regle.items())):
            regle_id = items[0].regle_id if items else ""
            correction = items[0].correction if items else ""

            html_content += f"""
<div class="section" id="detail-{regle_id}">
  <div class="section-header">
    <h3>{html.escape(key)}</h3>
    <span class="badge badge-anomalie">{len(items)} cas</span>
  </div>
  <div class="note-text">
    Correction suggérée : <em>{html.escape(correction)}</em>
  </div>
  <div class="section-body">
    <table>
      <thead>
        <tr>
          <th style="width:10%">Référence</th>
          <th style="width:5%">Ctx</th>
          <th>Extrait en contexte</th>
        </tr>
      </thead>
      <tbody>
"""
            for a in items:
                highlighted = _highlight_extrait(a.extrait, a.regle_id)
                html_content += f"""        <tr>
          <td class="ref">{html.escape(a.reference)}</td>
          <td class="ctx ctx-{html.escape(a.contexte)}">{html.escape(a.contexte)}</td>
          <td><span class="extrait">{highlighted}</span></td>
        </tr>
"""

            html_content += """      </tbody>
    </table>
  </div>
</div>
"""

    html_content += "</div>\n"

    # ═══════════════════════════════════════════════════════
    # ONGLET 4 — OBSERVATIONS
    # ═══════════════════════════════════════════════════════
    html_content += """
<div id="tab-observations" class="tab-content">
<h2>Observations</h2>
<p style="color: #78716c; font-size: 0.9rem; margin-bottom: 1rem;">
  Cas notables qui ne sont ni des anomalies ni des choix éditoriaux.
  Ce sont des usages spécifiques de la version, documentés ici pour référence.
</p>
"""

    if not observations:
        html_content += '<p style="color:var(--muted);font-style:italic;padding:2rem 0">Aucune observation détectée.</p>\n'
    else:
        for i, (key, items) in enumerate(sorted(par_obs.items())):
            regle_id = items[0].regle_id if items else ""
            correction = items[0].correction if items else ""

            html_content += f"""
<div class="section" id="obs-{regle_id}">
  <div class="section-header">
    <h3>{html.escape(key)}</h3>
    <span class="badge badge-obs">{len(items)} cas</span>
  </div>
  <div class="note-text">
    {html.escape(correction)}
  </div>
  <div class="section-body">
    <table>
      <thead>
        <tr>
          <th style="width:10%">Référence</th>
          <th style="width:5%">Ctx</th>
          <th>Extrait en contexte</th>
        </tr>
      </thead>
      <tbody>
"""
            for a in items:
                highlighted = _highlight_extrait(a.extrait, a.regle_id)
                html_content += f"""        <tr>
          <td class="ref">{html.escape(a.reference)}</td>
          <td class="ctx ctx-{html.escape(a.contexte)}">{html.escape(a.contexte)}</td>
          <td><span class="extrait">{highlighted}</span></td>
        </tr>
"""

            html_content += """      </tbody>
    </table>
  </div>
</div>
"""

    html_content += "</div>\n"

    # ═══════════════════════════════════════════════════════
    # SCRIPT + FOOTER
    # ═══════════════════════════════════════════════════════
    html_content += f"""
<footer>
  Généré par analyse_typo.py — maBible.app — Version analysée : {html.escape(nom_version)}
</footer>

<script>
function showTab(tabId) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(tabId).classList.add('active');
  event.target.classList.add('active');
}}
// Handle anchor links to anomaly/observation details
(function() {{
  var h = window.location.hash;
  if (h && h.startsWith('#detail-')) {{
    showTab('tab-anomalies');
    document.querySelectorAll('.nav-tab').forEach(function(t) {{ t.classList.remove('active'); }});
    document.querySelector('.nav-tab:nth-child(3)').classList.add('active');
  }} else if (h && h.startsWith('#obs-')) {{
    showTab('tab-observations');
    document.querySelectorAll('.nav-tab').forEach(function(t) {{ t.classList.remove('active'); }});
    document.querySelector('.nav-tab:nth-child(4)').classList.add('active');
  }}
}})();
</script>

</body>
</html>"""

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Rapport HTML généré : {filepath}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Analyse typographique des fichiers USX 3.0 — maBible.app",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python analyse_typo.py JHN.usx --version S21
  python analyse_typo.py --dossier ./S21/ --version S21
  python analyse_typo.py --dossier ./S21/ --version S21 --sortie rapport
        """,
    )
    parser.add_argument(
        'fichier', nargs='?',
        help="Fichier USX/XML à analyser",
    )
    parser.add_argument(
        '--dossier', '-d',
        help="Dossier contenant les fichiers USX à analyser",
    )
    parser.add_argument(
        '--version', '-v', required=True,
        help=f"Version biblique ({', '.join(PROFILS_VERSIONS.keys())})",
    )
    parser.add_argument(
        '--sortie', '-s', default='rapport_typo',
        help="Nom de base pour les fichiers de sortie (défaut: rapport_typo)",
    )

    args = parser.parse_args()

    if not args.fichier and not args.dossier:
        parser.error("Spécifiez un fichier ou un dossier (--dossier)")

    version = args.version.upper()
    if version not in PROFILS_VERSIONS:
        print(f"Version inconnue : {version}. Versions disponibles : {', '.join(PROFILS_VERSIONS.keys())}", file=sys.stderr)
        sys.exit(1)

    profil = PROFILS_VERSIONS[version]
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Analyse typographique — {profil['nom']} ({version})", file=sys.stderr)
    print(f"  Langue : {profil['langue']}", file=sys.stderr)
    print(f"  Choix éditoriaux actifs : {sum(1 for v in profil['choix_editoriaux'].values() if v)}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    # Analyse
    if args.dossier:
        anomalies = analyser_dossier(args.dossier, version)
    else:
        filepath = args.fichier
        if not os.path.exists(filepath):
            print(f"Fichier introuvable : {filepath}", file=sys.stderr)
            sys.exit(1)
        print(f"  Analyse de {filepath}…", file=sys.stderr)
        anomalies = analyser_fichier(filepath, version)

    # Séparer anomalies et observations
    vraies_anomalies = [a for a in anomalies if a.type == "anomalie"]
    observations = [a for a in anomalies if a.type == "observation"]

    # Résumé
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  RÉSULTAT : {len(vraies_anomalies)} anomalies, {len(observations)} observations", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    if vraies_anomalies:
        print("  Anomalies :", file=sys.stderr)
        par_regle: dict[str, int] = {}
        for a in vraies_anomalies:
            key = f"  {a.regle_id} — {a.anomalie}"
            par_regle[key] = par_regle.get(key, 0) + 1
        for key, count in sorted(par_regle.items()):
            print(f"  {key} : {count} cas", file=sys.stderr)

    if observations:
        print("  Observations :", file=sys.stderr)
        par_obs: dict[str, int] = {}
        for a in observations:
            key = f"  {a.regle_id} — {a.anomalie}"
            par_obs[key] = par_obs.get(key, 0) + 1
        for key, count in sorted(par_obs.items()):
            print(f"  {key} : {count} cas", file=sys.stderr)

    if anomalies:
        # Génération des rapports
        csv_path = f"{args.sortie}.csv"
        html_path = f"{args.sortie}.html"

        generer_csv(anomalies, csv_path)
        generer_html(anomalies, html_path, version)

        print(f"\nTerminé. Rapports : {csv_path}, {html_path}", file=sys.stderr)
    else:
        print("  Aucune anomalie ni observation détectée.", file=sys.stderr)


if __name__ == "__main__":
    main()
