from scripts.validate_seed_schema import validate_companies


def test_validate_companies_valid():
    sample = [
        {
            "company_name": "Stripe",
            "career_url": "https://boards.greenhouse.io/stripe",
            "ats_platform": "greenhouse",
            "ats_identifier": "stripe",
        },
        {
            "company_name": "Adobe",
            "career_url": "https://adobe.wd5.myworkdayjobs.com/Careers",
            "ats_platform": "workday",
            "ats_identifier": "adobe|wd5|Careers",
        },
    ]
    errors = validate_companies(sample)
    assert errors == []


def test_validate_companies_missing_name():
    sample = [
        {
            "company_name": "",
            "career_url": "https://jobs.lever.co/test",
            "ats_platform": "lever",
            "ats_identifier": "test",
        }
    ]
    errors = validate_companies(sample)
    assert len(errors) == 1
    assert "missing or empty 'company_name'" in errors[0]


def test_validate_companies_unsupported_platform():
    sample = [
        {
            "company_name": "Acme",
            "career_url": "https://acme.com",
            "ats_platform": "unsupported_ats",
            "ats_identifier": "acme",
        }
    ]
    errors = validate_companies(sample)
    assert any("unsupported 'ats_platform'" in e for e in errors)


def test_validate_companies_invalid_workday_format():
    sample = [
        {
            "company_name": "Corp",
            "career_url": "https://corp.myworkdayjobs.com",
            "ats_platform": "workday",
            "ats_identifier": "invalid_workday_id",
        }
    ]
    errors = validate_companies(sample)
    assert any("invalid Workday identifier" in e for e in errors)


def test_validate_companies_duplicate_keys():
    sample = [
        {
            "company_name": "Stripe EU",
            "career_url": "https://boards.greenhouse.io/stripe",
            "ats_platform": "greenhouse",
            "ats_identifier": "stripe",
        },
        {
            "company_name": "Stripe US",
            "career_url": "https://boards.greenhouse.io/stripe",
            "ats_platform": "greenhouse",
            "ats_identifier": "stripe",
        },
    ]
    errors = validate_companies(sample)
    assert any("duplicate platform/identifier tuple" in e for e in errors)
