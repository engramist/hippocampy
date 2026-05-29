class Hippocampy < Formula
  include Language::Python::Virtualenv

  desc "AI memory that learns from every conversation"
  homepage "https://github.com/djs54/hippocampy"
  url "https://files.pythonhosted.org/packages/source/h/hippocampy/hippocampy-0.1.0.tar.gz"
  sha256 "PLACEHOLDER_SHA256"
  license "Apache-2.0"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  def post_install
    system bin/"campy", "setup"
  end

  def caveats
    <<~EOS
      To start the Campy brain daemon:
        campy start

      To check status:
        campy status

      To re-register with AI agents:
        campy setup
    EOS
  end

  test do
    assert_match "HippoCampy", shell_output("#{bin}/campy --help")
  end
end