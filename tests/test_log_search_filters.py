import pytest

from app.log_search_filters import FilterValidationError, parse_ip_entries, parse_port_entries


def test_parse_single_ipv4():
    assert parse_ip_entries("10.1.1.5", "srcip") == ["srcip==10.1.1.5"]


def test_parse_single_ipv6():
    assert parse_ip_entries("2001:db8::1", "dstip") == ["dstip==2001:db8::1"]


def test_parse_cidr():
    assert parse_ip_entries("10.1.1.0/24", "srcip") == ["srcip==10.1.1.0/24"]


def test_parse_explicit_range():
    assert parse_ip_entries("10.1.1.1-10.1.1.10", "srcip") == [
        "(srcip>=10.1.1.1 and srcip<=10.1.1.10)"
    ]


def test_parse_multiple_entries():
    result = parse_ip_entries("10.1.1.5, 10.1.2.0/24", "srcip")
    assert result == ["srcip==10.1.1.5", "srcip==10.1.2.0/24"]


def test_parse_ip_rejects_invalid_address():
    with pytest.raises(FilterValidationError, match="not-an-ip"):
        parse_ip_entries("not-an-ip", "srcip")


def test_parse_ip_rejects_mismatched_range_versions():
    with pytest.raises(FilterValidationError, match="same IP version"):
        parse_ip_entries("10.1.1.1-2001:db8::1", "srcip")


def test_parse_ip_rejects_backwards_range():
    with pytest.raises(FilterValidationError, match="greater than end"):
        parse_ip_entries("10.1.1.10-10.1.1.1", "srcip")


def test_parse_ip_empty_returns_empty_list():
    assert parse_ip_entries("", "srcip") == []


def test_parse_ip_any_returns_empty_list():
    assert parse_ip_entries("ANY", "srcip") == []
    assert parse_ip_entries("any", "srcip") == []
    assert parse_ip_entries("All", "srcip") == []


def test_parse_ip_any_mixed_with_real_entries_skips_only_any():
    assert parse_ip_entries("ANY, 10.1.1.5", "srcip") == ["srcip==10.1.1.5"]


def test_parse_port_numeric():
    assert parse_port_entries("443") == ["dstport==443"]


def test_parse_port_proto_prefixed():
    assert parse_port_entries("tcp:443") == ["dstport==443"]
    assert parse_port_entries("udp:53") == ["dstport==53"]


def test_parse_port_range():
    assert parse_port_entries("tcp:1000-1200") == ["(dstport>=1000 and dstport<=1200)"]


def test_parse_port_service_name():
    assert parse_port_entries("HTTPS") == ['service=="HTTPS"']


def test_parse_port_multiple_entries():
    assert parse_port_entries("443, HTTPS") == ["dstport==443", 'service=="HTTPS"']


def test_parse_port_rejects_backwards_range():
    with pytest.raises(FilterValidationError, match="greater than end"):
        parse_port_entries("tcp:1200-1000")


def test_parse_port_empty_returns_empty_list():
    assert parse_port_entries("") == []


def test_parse_port_any_returns_empty_list():
    assert parse_port_entries("ANY") == []
    assert parse_port_entries("all") == []


def test_parse_port_rejects_injection_in_service_name():
    with pytest.raises(FilterValidationError, match="Invalid port/service entry"):
        parse_port_entries('HTTPS" or srcip>="0.0.0.0')


def test_parse_port_rejects_malformed_range_as_service_name():
    with pytest.raises(FilterValidationError, match="Invalid port/service entry"):
        parse_port_entries("tcp:abc-def")
