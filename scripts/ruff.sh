#!/bin/bash

uv run ruff check --fix
uv run ruff format
git add -p
git commit -m "ruff fix"