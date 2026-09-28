"""Turns a material's text into flashcards grouped by concept.

chunking -> embeddings -> clustering -> generators (Gemini, Claude or rules) -> quality
filters, tied together in pipeline.py. Each stage can be tested on its own.
"""
