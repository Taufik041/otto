import pytest

from shared.github import parse_repo


@pytest.mark.parametrize("url", [
    "https://github.com/Taufik041/otto_test",
    "https://github.com/Taufik041/otto_test.git",
    "https://github.com/Taufik041/otto_test/",
    "https://github.com/Taufik041/otto_test.git/",
    "http://github.com/Taufik041/otto_test",
    "https://x-access-token:ghs_abc@github.com/Taufik041/otto_test.git",
    "git@github.com:Taufik041/otto_test.git",
    "ssh://git@github.com/Taufik041/otto_test.git",
    "  https://github.com/Taufik041/otto_test\n",
])
def test_parse_repo(url):
    assert parse_repo(url) == ("Taufik041", "otto_test")


def test_parse_repo_keeps_dots_inside_the_name():
    assert parse_repo("https://github.com/o/my.repo.git") == ("o", "my.repo")


@pytest.mark.parametrize("url", [None, "", "https://github.com/onlyowner", "not a url",
                                 "https://github.com/o/r/pulls", "file:///tmp/r.git"])
def test_parse_repo_rejects_other_urls(url):
    with pytest.raises(ValueError):
        parse_repo(url)
