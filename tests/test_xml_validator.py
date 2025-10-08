import textwrap

import pytest

pytest.importorskip("xmlschema")

from app.services import xml_validator


VALID_XML = textwrap.dedent(
    """
    <?xml version="1.0" encoding="UTF-8"?>
    <ProductTitleResult>
      <Order>
        <OrderNumber>123456</OrderNumber>
      </Order>
      <TitleData>
        <Title>
          <TitleNumber>002345678901</TitleNumber>
          <Type>Title</Type>
          <RightsType>Surface</RightsType>
          <Consolidated>false</Consolidated>
          <CreateDate>2024-01-01</CreateDate>
          <RegistrationDetails>
            <DocumentNumber>0</DocumentNumber>
            <Date>2024-01-01</Date>
            <DocumentType>
              <Code>TFR</Code>
              <Name>TRANSFER</Name>
            </DocumentType>
          </RegistrationDetails>
          <Parcels>
            <Parcel>
              <LINCNumber>1234567890</LINCNumber>
              <ShortLegalType>ATS</ShortLegalType>
              <ShortLegal>LOT 1 BLOCK 2 PLAN 1234</ShortLegal>
            </Parcel>
          </Parcels>
          <Owners>
            <TenancyGroup>
              <TenancyType>Joint Tenants</TenancyType>
              <Parties>
                <Party>
                  <Name>DOE JOHN</Name>
                  <Type>Individual</Type>
                </Party>
              </Parties>
            </TenancyGroup>
          </Owners>
          <AffectingInstruments>
            <Document>
              <RegistrationNumber>123456789012</RegistrationNumber>
              <DocumentType>
                <Code>MTGE</Code>
                <Name>MORTGAGE</Name>
              </DocumentType>
            </Document>
          </AffectingInstruments>
        </Title>
      </TitleData>
    </ProductTitleResult>
    """
).strip()


INVALID_XML = VALID_XML.replace("002345678901", "1234567890123")


@pytest.fixture(autouse=True)
def reset_cache():
    xml_validator.reset_schema_cache()
    yield
    xml_validator.reset_schema_cache()


def test_validate_success():
    ok, errors = xml_validator.validate(VALID_XML)
    assert ok is True
    assert errors == []


def test_validate_failure_reports_xpath():
    ok, errors = xml_validator.validate(INVALID_XML)
    assert ok is False
    assert errors
    assert any("TitleNumber" in err["message"] for err in errors)
    assert all("xpath" in err for err in errors)
