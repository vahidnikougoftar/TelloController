"""Keyboard polling helper for pygame demos."""

from __future__ import annotations

import pygame


def init() -> None:
    pygame.init()
    pygame.display.set_mode((400, 400))
    pygame.display.set_caption("Key Press Module")


def get_key_events(key_name: str) -> bool:
    """Return True when the requested key is pressed."""
    key_input = pygame.key.get_pressed()
    key = getattr(pygame, f"K_{key_name}")
    pressed = bool(key_input[key])
    pygame.display.update()
    return pressed


if __name__ == "__main__":
    init()
