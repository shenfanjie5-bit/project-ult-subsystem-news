from __future__ import annotations

from subsystem_news.normalize.html_strip import strip_boilerplate


def test_strip_boilerplate_removes_template_noise_and_scripts() -> None:
    html = """
    <html>
      <head><style>.x{color:red}</style><script>alert("x")</script></head>
      <body>
        <header>Subscribe</header>
        <nav>Markets Sports</nav>
        <article>
          <h1>Plant restart update</h1>
          <p>North River Metals restarted its nickel plant.</p>
          <p>Output should recover this quarter.</p>
        </article>
        <footer>Contact us</footer>
      </body>
    </html>
    """

    text = strip_boilerplate(html)

    assert "North River Metals restarted its nickel plant." in text
    assert "Output should recover this quarter." in text
    assert "alert" not in text
    assert "Subscribe" not in text
    assert "Markets Sports" not in text
    assert "Contact us" not in text
    assert "<p>" not in text
