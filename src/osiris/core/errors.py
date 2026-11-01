"""Exceptions OSIRIS."""

from __future__ import annotations


class OsirisError(Exception):
    """Erreur de base OSIRIS."""


class InvalidInput(OsirisError):
    """Entree invalide ou malformee."""


class AccessDenied(OsirisError):
    """Acces refuse (chemin hors racine autorisee, taille excessive...)."""


class IntegrityError(OsirisError):
    """Le contenu stocke ne correspond plus a son hash."""


class BudgetExceeded(OsirisError):
    """Budget epuise."""


class TaskNotFound(OsirisError):
    """Tache inconnue."""
