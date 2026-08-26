"""Konwersja zapisów równoważnych na MathJSON (G2.6).

Normalizacja po stronie Pythona, parsowanie w Node — bo `@cortex-js/compute-engine`
jest referencyjną implementacją MathJSON i tym samym silnikiem, którego użyje
EvaluateClosed w A3. Parsowanie tą samą biblioteką eliminuje dryf dialektu
między ingestem a silnikiem oceniania.
"""
