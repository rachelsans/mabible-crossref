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
    """Représente une anomalie typographique détectée."""
    livre: str
    reference: str
    extrait: str
    anomalie: str
    correction: str
    regle_id: str
    contexte: str  # 'texte' ou 'note'
    position: int = 0  # position dans le texte pour le surlignage


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
    },
    # Profils extensibles pour d'autres versions
    "LSG": {
        "langue": "FR",
        "nom": "Louis Segond 1910",
        "choix_editoriaux": {},
    },
    "NBS": {
        "langue": "FR",
        "nom": "Nouvelle Bible Segond",
        "choix_editoriaux": {},
    },
    "NIV": {
        "langue": "EN",
        "nom": "New International Version",
        "choix_editoriaux": {},
    },
    "RVR": {
        "langue": "ES",
        "nom": "Reina Valera Revisada",
        "choix_editoriaux": {},
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
    regles.append({
        "id": "R-FR-03",
        "nom": "Triple point au lieu de …",
        "pattern": re.compile(r'\.{3}'),
        "description": "Trois points au lieu du caractère … (U+2026)",
        "correction": "Remplacer ... par … (U+2026)",
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
            "pattern": re.compile(r"(?<=[a-zA-ZÀ-ÿ])'(?=[a-zA-ZÀ-ÿ])"),
            "description": "Apostrophe droite U+0027 au lieu de typographique U+2019",
            "correction": "Remplacer ' (U+0027) par \u2019 (U+2019)",
        })
    else:
        # Si la version utilise U+0027, détecter les U+2019 résiduels comme apostrophe
        regles.append({
            "id": "R-FR-08b",
            "nom": "Apostrophe typographique résiduelle",
            "pattern": re.compile(r"(?<=[a-zA-ZÀ-ÿ])\u2019(?=[a-zA-ZÀ-ÿ])"),
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
    """Texte d'un verset avec sa référence."""
    livre: str
    chapitre: str
    verset: str
    texte: str
    contexte: str  # 'texte' ou 'note'

    @property
    def reference(self) -> str:
        return f"{self.livre} {self.chapitre}:{self.verset}"


def parse_usx(filepath: str) -> list[VerseText]:
    """Parse un fichier USX 3.0 et retourne une liste de VerseText.

    Stratégie : parcours linéaire de tous les éléments XML, en suivant
    le chapitre/verset courant et en segmentant le texte par verset.
    Les notes sont collectées séparément avec leur propre contexte.
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Déterminer le code du livre
    book_elem = root.find('.//book')
    livre = book_elem.attrib.get('code', 'UNK') if book_elem is not None else 'UNK'

    versets: list[VerseText] = []
    current_chapter = "0"
    current_verse = "0"

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
                    contexte='texte',
                ))
            text_buffer = []

    def process_element(elem):
        """Traite un élément et ses enfants, en suivant chapitre/verset."""
        nonlocal current_chapter, current_verse, text_buffer

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
            if style in ('id', 'ide', 'h', 'toc1', 'toc2', 'toc3', 'rem'):
                return

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


def generer_html(anomalies: list[Anomalie], filepath: str, version: str):
    """Génère un rapport HTML lisible avec anomalies surlignées."""
    profil = PROFILS_VERSIONS.get(version, {})
    nom_version = profil.get("nom", version)

    # Regrouper par livre puis par règle
    par_regle: dict[str, list[Anomalie]] = {}
    for a in anomalies:
        key = f"{a.regle_id} — {a.anomalie}"
        par_regle.setdefault(key, []).append(a)

    # Compter par livre
    par_livre: dict[str, int] = {}
    for a in anomalies:
        par_livre[a.livre] = par_livre.get(a.livre, 0) + 1

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
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.75rem;
    margin-bottom: 0.25rem;
  }}
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
    min-width: 140px;
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
    cursor: pointer;
    user-select: none;
  }}
  .section-header:hover {{
    background: #f5f5f4;
  }}
  .section-header h2 {{
    font-size: 1rem;
    font-weight: 600;
  }}
  .section-header .count {{
    background: var(--accent-bg);
    color: var(--accent);
    border: 1px solid var(--accent-border);
    border-radius: 999px;
    padding: 0.15rem 0.75rem;
    font-size: 0.85rem;
    font-weight: 600;
  }}
  .section-body {{
    padding: 0;
  }}
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
  tr:last-child td {{
    border-bottom: none;
  }}
  .ref {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.85rem;
    color: var(--blue);
    white-space: nowrap;
  }}
  .ctx {{
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
  }}
  .extrait {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.85rem;
    background: #f5f5f4;
    padding: 0.3rem 0.5rem;
    border-radius: 4px;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  mark {{
    background: #fde047;
    padding: 0.1rem 0.2rem;
    border-radius: 2px;
  }}
  .correction {{
    font-size: 0.85rem;
    color: var(--muted);
    font-style: italic;
  }}
  .toc {{
    margin-bottom: 2rem;
  }}
  .toc a {{
    color: var(--blue);
    text-decoration: none;
    font-size: 0.9rem;
  }}
  .toc a:hover {{
    text-decoration: underline;
  }}
  .toc ul {{
    list-style: none;
    padding-left: 0;
  }}
  .toc li {{
    padding: 0.2rem 0;
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

<div class="stats">
  <div class="stat-card">
    <div class="number">{len(anomalies)}</div>
    <div class="label">anomalies détectées</div>
  </div>
  <div class="stat-card">
    <div class="number">{len(par_regle)}</div>
    <div class="label">types d'anomalies</div>
  </div>
  <div class="stat-card">
    <div class="number">{len(par_livre)}</div>
    <div class="label">livres concernés</div>
  </div>
</div>

<div class="toc">
<h3>Sommaire</h3>
<ul>
"""

    for i, (key, items) in enumerate(sorted(par_regle.items())):
        anchor = f"section-{i}"
        html_content += f'  <li><a href="#{anchor}">{html.escape(key)} ({len(items)} cas)</a></li>\n'

    html_content += """</ul>
</div>
"""

    for i, (key, items) in enumerate(sorted(par_regle.items())):
        anchor = f"section-{i}"
        correction = items[0].correction if items else ""

        html_content += f"""
<div class="section" id="{anchor}">
  <div class="section-header">
    <h2>{html.escape(key)}</h2>
    <span class="count">{len(items)} cas</span>
  </div>
  <div class="section-body">
    <p style="padding: 0.75rem 1rem; color: #78716c; font-size: 0.85rem; border-bottom: 1px solid #e7e5e4;">
      Correction : {html.escape(correction)}
    </p>
    <table>
      <thead>
        <tr>
          <th>Référence</th>
          <th>Ctx</th>
          <th>Extrait</th>
        </tr>
      </thead>
      <tbody>
"""
        for a in items:
            escaped_extrait = html.escape(a.extrait)
            html_content += f"""        <tr>
          <td class="ref">{html.escape(a.reference)}</td>
          <td class="ctx">{html.escape(a.contexte)}</td>
          <td><span class="extrait">{escaped_extrait}</span></td>
        </tr>
"""

        html_content += """      </tbody>
    </table>
  </div>
</div>
"""

    html_content += f"""
<footer>
  Généré par analyse_typo.py — maBible.app — Version analysée : {html.escape(nom_version)}
</footer>

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

    # Résumé
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  RÉSULTAT : {len(anomalies)} anomalies détectées", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    if anomalies:
        # Résumé par type
        par_regle: dict[str, int] = {}
        for a in anomalies:
            key = f"{a.regle_id} — {a.anomalie}"
            par_regle[key] = par_regle.get(key, 0) + 1

        for key, count in sorted(par_regle.items()):
            print(f"  {key} : {count} cas", file=sys.stderr)

        # Génération des rapports
        csv_path = f"{args.sortie}.csv"
        html_path = f"{args.sortie}.html"

        generer_csv(anomalies, csv_path)
        generer_html(anomalies, html_path, version)

        print(f"\nTerminé. Rapports : {csv_path}, {html_path}", file=sys.stderr)
    else:
        print("  Aucune anomalie détectée.", file=sys.stderr)


if __name__ == "__main__":
    main()
