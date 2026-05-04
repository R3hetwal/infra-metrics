# How to publish infra-metrics

Two options depending on your company setup:
- **Option A** — Private PyPI (recommended for companies, no public exposure)
- **Option B** — Public PyPI (fine if code is not sensitive)

Both use the same package. GitHub hosts the code; PyPI (or your private registry) hosts the installable wheel.

---

## 1. Push to GitHub

```bash
cd infra_metrics

git init
git add .
git commit -m "feat: initial release"

# Create a repo on github.com first (can be private), then:
git remote add origin https://github.com/YOUR-ORG/infra-metrics.git
git branch -M main
git push -u origin main
```

That's it. GitHub Actions will run tests automatically on every push.

---

## 2A. Private PyPI (company internal — recommended)

Use this if you don't want the package publicly visible.

### Option: GitHub Packages (simplest for GitHub orgs)

```bash
# Install build tools
pip install build twine

# Build the wheel
python -m build
# → creates dist/infra_metrics-0.1.0-py3-none-any.whl
#            dist/infra_metrics-0.1.0.tar.gz

# Publish to GitHub Packages
twine upload \
  --repository-url https://maven.pkg.github.com/YOUR-ORG/infra-metrics \
  --username YOUR-GITHUB-USERNAME \
  --password YOUR-GITHUB-TOKEN \       # needs write:packages scope
  dist/*
```

#### Anyone in your org installs it:
```bash
pip install infra-metrics \
  --index-url https://YOUR-GITHUB-USERNAME:YOUR-TOKEN@maven.pkg.github.com/YOUR-ORG/infra-metrics/simple/
```

Or add to `pip.conf` / `~/.pip/pip.conf` so you don't repeat the URL:
```ini
[global]
extra-index-url = https://YOUR-TOKEN@maven.pkg.github.com/YOUR-ORG/infra-metrics/simple/
```

### Option: AWS CodeArtifact / Azure Artifacts / JFrog

Same `twine upload` command but point `--repository-url` at your registry URL.
Credentials from your cloud provider instead of GitHub token.

---

## 2B. Public PyPI

Only do this if the monitoring code itself has no sensitive logic.

### One-time setup on pypi.org

1. Create account at https://pypi.org
2. Go to Account → API Tokens → Add token (scope: entire account or specific project)
3. Add token to GitHub repo: Settings → Secrets → `PYPI_API_TOKEN`

### Release a new version

```bash
# Bump version in pyproject.toml first:
# version = "0.2.0"

git add pyproject.toml
git commit -m "chore: bump version to 0.2.0"

# Tag triggers the publish GitHub Action automatically
git tag v0.2.0
git push origin main --tags
```

GitHub Action builds + publishes to PyPI. Done.

#### Anyone installs it (no token needed):
```bash
pip install infra-metrics          # CPU only
pip install "infra-metrics[gpu]"   # with GPU support
```

---

## Version bump checklist

1. Edit `version = "x.y.z"` in `pyproject.toml`
2. Update `CHANGELOG.md` (optional but good)
3. Commit + tag: `git tag vX.Y.Z && git push --tags`
4. GitHub Action handles the rest

---

## Semver convention

| Change | Version bump | Example |
|---|---|---|
| Bug fix | patch | 0.1.0 → 0.1.1 |
| New feature, backward compatible | minor | 0.1.0 → 0.2.0 |
| Breaking change | major | 0.1.0 → 1.0.0 |
