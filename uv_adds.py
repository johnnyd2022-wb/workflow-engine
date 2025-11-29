while read pkg; do
    # Use uv add to add the package to pyproject.toml
    uv add "$pkg"
done < requirements.txt
