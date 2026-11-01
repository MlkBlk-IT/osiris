"""Sous-package du dashboard OSIRIS (Control Plane).

Ce fichier existe pour que le dashboard soit importable comme
`osiris.dashboard.server` une fois installe en paquet (wheel) : le binaire
`osiris-dashboard` y pointe.

Ne pas importer ici : le dashboard lit la base en lecture seule.
"""
