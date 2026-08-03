# Campy (HippoCampy) Homebrew formula.
#
# STATUS: draft, pending public package publication (see backlog/B236.md).
# Campy is not yet published on PyPI and the source repository is not yet
# public, so `url`/`sha256` below are placeholders and this formula cannot
# be installed from the internet yet. It is validated locally instead:
#
#   bash scripts/validate_homebrew_formula.sh
#
# That script builds a local sdist, resolves this formula against the local
# file (swapping `url`/`sha256` for the freshly-built artifact), and runs
# `brew audit --strict` plus `brew install --build-from-source` against the
# resolved copy. Once B236 (PyPI publish) lands and a release is tagged,
# replace the placeholders below with the real PyPI URL and its sha256
# (e.g. from `twine upload` output or `pip hash dist/hippocampy-*.tar.gz`)
# and drop this comment block.
#
# This formula intentionally does nothing beyond installing the `campy` CLI
# into an isolated virtualenv. It does not create `~/.campy`, does not start
# the daemon, and does not register with any AI client — see `caveats` below
# for the commands that do that, on request, after install.
#
# Note on `install`: this does NOT use Homebrew's usual
# `virtualenv_install_with_resources` helper. That helper forces
# `pip install --no-deps --no-binary=:all:`, which requires every
# transitive dependency to be declared as a formula `resource` and built
# from source. Campy's dependency graph includes heavy ML packages
# (sentence-transformers/torch, spacy, kuzu) with no practical from-source
# Homebrew resource story — hand-maintaining 100+ pinned resource stanzas
# for them is infeasible and would drift on every dependency bump. Instead,
# `install` below creates the virtualenv and lets pip resolve dependencies
# from PyPI as prebuilt wheels, same as `pipx install hippocampy` would.
# This was verified locally (see scripts/validate_homebrew_formula.sh) —
# `brew install --build-from-source` completes in about a minute using
# published wheels, no compilation required.
class Hippocampy < Formula
  include Language::Python::Virtualenv

  desc "Local-first, graph-native AI memory for coding agents"
  homepage "https://github.com/engramist/hippocampy"
  url "https://files.pythonhosted.org/packages/source/h/hippocampy/hippocampy-0.1.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000" # PLACEHOLDER: not yet published, see B236 (must be 64 hex chars)
  license "Apache-2.0"

  depends_on "python@3.12"

  def install
    virtualenv_create(libexec, "python3.12")
    system "python3.12", "-m", "pip", "--python=#{libexec}/bin/python",
           "install", "--no-cache-dir", buildpath
    bin.install_symlink Dir[libexec/"bin/campy*"]
  end

  def caveats
    <<~EOS
      `brew install` only installed the campy CLI into an isolated
      virtualenv. It did not create ~/.campy, start the memory daemon, or
      register with any AI client — none of that is safe to do unattended
      during a package install.

      Finish setup with:
        campy install     Full one-command setup: LLM provider, database,
                           adapters, daemon, and per-agent plugin skills.
        campy setup        Detect and (re-)register with installed AI
                           clients only (Claude Code, Codex, Gemini CLI, ...).
        campy doctor        Diagnose an existing install and repair common
                           problems (missing launchd plist, stale client
                           config, missing skill files, etc).
        campy doctor --repair
                           Attempt automatic repair of what `doctor` finds.

      `brew uninstall hippocampy` only removes the CLI. It never touches
      ~/.campy (your memory database, journals, and activity log). To remove
      Campy's AI client registrations and/or memory data explicitly, run
      `campy uninstall --help` before or after `brew uninstall`.

      See docs/homebrew-install.md for the full install/repair/uninstall
      walkthrough.
    EOS
  end

  test do
    assert_match "HippoCampy", shell_output("#{bin}/campy --help")
  end
end
