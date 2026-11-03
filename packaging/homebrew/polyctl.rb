# Homebrew formula. Copy into a tap (homebrew-<name>/Formula/) and update `url`
# and `sha256` for each release — see packaging/RELEASING.md.
#
# No `resource` blocks because there are no dependencies, which is the point: the
# virtualenv holds one package and nothing can drift underneath it.
class Polyctl < Formula
  include Language::Python::Virtualenv

  desc "Your agents commit, every change is granted first or flagged"
  homepage "https://hakkisagdic.github.io/polyctl/"
  url "https://github.com/hakkisagdic/polyctl/archive/refs/tags/v0.7.0.tar.gz"
  sha256 "c64478c9116c1e3ff720a8ff2a5f5596380ddfdf6280f6577450186f506a69ac"
  license "MIT"
  head "https://github.com/hakkisagdic/polyctl.git", branch: "main"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
    bin.install_symlink "polyctl" => "pctl" unless (bin/"pctl").exist?
  end

  test do
    # `adapters` reads packaged data, so it fails loudly if the JSON files did not
    # ship — the one packaging mistake that a plain `--help` would not catch.
    assert_equal shell_output("#{bin}/polyctl --version"), shell_output("#{bin}/pctl --version")
    assert_match "usage: pctl", shell_output("#{bin}/pctl --help")
    assert_match "kiro", shell_output("#{bin}/polyctl adapters")
    assert_match "usage", shell_output("#{bin}/polyctl lock")
  end
end
