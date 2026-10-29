from app.extract import (
    ServerLink,
    candidate_server_urls,
    detail_metadata,
    extract_media_urls,
    extract_server_links,
    parse_search_results,
    rewrite_m3u8,
)
from app.security import UnsafeUrl, ensure_public_url


def test_search_parser_deduplicates_cards_and_loads_lazy_poster():
    source = """
    <article class="video-item">
      <a href="/350766.html" title="JUR-583 中文字幕">
        <img data-original="https://img.example/poster.jpg" alt="JUR-583 中文字幕">
      </a><span class="tag">中文字幕</span>
      <a href="/350766.html">details</a>
    </article>
    """
    items = parse_search_results(source, "https://supjav.com/?s=JUR-583")
    assert len(items) == 1
    assert items[0]["code"] == "JUR-583"
    assert items[0]["poster"] == "https://img.example/poster.jpg"
    assert items[0]["playable"] is True


def test_server_and_media_extraction_handles_escaped_urls():
    source = """
    <button class="btn-server" data-link="abc">EVS</button>
    <iframe src="https://player.example/embed/1"></iframe>
    <script>const p={file:"https:\\/\\/cdn.example\\/a\\/master.m3u8?token=x"};</script>
    """
    assert extract_server_links(source, "https://supjav.com/350766.html") == [ServerLink("EVS", "abc")]
    assert extract_media_urls(source, "https://player.example/embed/1") == [
        "https://cdn.example/a/master.m3u8?token=x"
    ]


def test_candidate_server_urls_supports_legacy_wrapper():
    urls = candidate_server_urls(ServerLink("EVS", "abc123"), "https://supjav.com/350766.html")
    assert "https://lk1.supremejav.com/supjav.php?c=abc123" in urls
    assert "https://lk1.supremejav.com/supjav.php?c=321cba" in urls


def test_m3u8_rewrite_covers_segments_variants_keys_and_maps():
    playlist = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXT-X-MAP:URI='init.mp4'
#EXTINF:4,
seg-1.ts
low/index.m3u8
"""
    registered = []

    def register(url):
        registered.append(url)
        return "/proxy/" + str(len(registered))

    output = rewrite_m3u8(playlist, "https://cdn.example/path/master.m3u8", register)
    assert "URI=\"/proxy/1\"" in output
    assert "URI='/proxy/2'" in output
    assert "/proxy/3" in output
    assert "/proxy/4" in output
    assert registered == [
        "https://cdn.example/path/key.bin",
        "https://cdn.example/path/init.mp4",
        "https://cdn.example/path/seg-1.ts",
        "https://cdn.example/path/low/index.m3u8",
    ]


def test_ssrf_guard_rejects_private_literal():
    try:
        ensure_public_url("http://127.0.0.1/admin", resolve_dns=False)
        assert False, "private URL should fail"
    except UnsafeUrl:
        pass


def test_detail_metadata_keeps_source_taxonomy_identity():
    source = """
    <meta property="og:image" content="/covers/a.jpg">
    <a href="/zh/actress/yuka">新妻ゆうか</a>
    <a href="/zh/actress/yuka">新妻ゆうか</a>
    <a href="/zh/genre/chinese-subtitles">中文字幕</a>
    """
    data = detail_metadata(source, "https://supjav.com/350766.html")
    assert data["poster"] == "https://supjav.com/covers/a.jpg"
    assert data["actors"] == [{"id": "yuka", "name": "新妻ゆうか", "type": "sup-actor"}]
    assert data["genres"][0]["name"] == "中文字幕"
    assert data["hasChineseSubtitles"] is True

