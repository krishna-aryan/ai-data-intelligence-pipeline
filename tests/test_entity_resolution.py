from src.entity_resolution import EntityResolver, normalize_name


def test_openai_name_variants_resolve_to_openai():
    resolver = EntityResolver()
    assert resolver.resolve_startup("OpenAI").canonical_name == "OpenAI"
    assert resolver.resolve_startup("openai").canonical_name == "OpenAI"
    assert resolver.resolve_startup("Open AI").canonical_name == "OpenAI"
    assert resolver.resolve_startup("OpenAI, Inc.").canonical_name == "OpenAI"


def test_whitespace_normalization():
    assert normalize_name("  Open   AI  ") == "open ai"


def test_punctuation_normalization():
    assert normalize_name("OpenAI, Inc.") == "openai"


def test_legal_suffix_removal():
    assert normalize_name("OpenAI Inc.") == "openai"
    assert normalize_name("Anthropic LLC") == "anthropic"


def test_known_alias_matches_canonical_entity():
    resolver = EntityResolver()
    result = resolver.resolve_startup("Anthropic AI")
    assert result.canonical_name == "Anthropic"
    assert result.match_type == "exact_alias"


def test_unknown_company_is_unresolved():
    resolver = EntityResolver()
    result = resolver.resolve_startup("Some Unknown AI Company")
    assert result.canonical_name is None
    assert result.status == "unresolved"


def test_original_name_is_preserved():
    resolver = EntityResolver()
    result = resolver.resolve_startup("OpenAI, Inc.")
    assert result.original_name == "OpenAI, Inc."


def test_normalized_name_is_deterministic():
    assert normalize_name("OpenAI") == "openai"
    assert normalize_name("openai") == "openai"
    assert normalize_name("Open AI") == "open ai"


def test_mapping_result_has_reason():
    resolver = EntityResolver()
    result = resolver.resolve_startup("Open AI")
    assert result.reason
    assert "match" in result.reason.lower()


def test_mapping_log_contains_source_url_when_supplied():
    resolver = EntityResolver()
    result = resolver.resolve_startup("OpenAI", source_url="https://example.com")
    log = resolver.build_mapping_log(result, source_url="https://example.com")
    assert log.source_url == "https://example.com"
    assert log.canonical_name == "OpenAI"


def test_product_names_do_not_get_incorrectly_merged():
    resolver = EntityResolver()
    result = resolver.resolve_product("OpenAI ChatGPT")
    assert result.status == "unresolved"
    assert result.canonical_name is None


def test_resolver_does_not_use_an_llm_or_probabilistic_matcher():
    resolver = EntityResolver()
    result = resolver.resolve_startup("Open AI")
    assert result.match_type in {"exact_canonical", "exact_alias", "unresolved"}
    assert result.canonical_name in {"OpenAI", None}


def test_repeated_resolution_is_stable():
    resolver = EntityResolver()
    first = resolver.resolve_startup("Open AI")
    second = resolver.resolve_startup("Open AI")
    assert first.model_dump() == second.model_dump()


def test_seed_data_is_separate_from_resolver_logic():
    from src.entity_resolution.seed_data import SEED_ENTITIES

    assert isinstance(SEED_ENTITIES, list)
    assert any(entry["canonical_name"] == "OpenAI" for entry in SEED_ENTITIES)
