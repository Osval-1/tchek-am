from typing import Literal

from pydantic import BaseModel
from pydantic.json_schema import SkipJsonSchema

EvidenceKind = Literal["chat", "momo_sms", "post", "other"]
ScamType = Literal["momo_fraud", "fake_product", "advance_fee", "other"]
Operator = Literal["mtn", "orange", "nexttel", "camtel", "unknown"]


class AccountNameItem(BaseModel):
    name: str
    provider: Literal["momo", "om", "unknown"]


class Extraction(BaseModel):
    """What the vision model read from a report's evidence. Values are as shown, never inferred."""

    phone_numbers: list[str]
    account_names: list[AccountNameItem]
    amounts_xaf: list[int]
    transaction_ids: list[str]
    dates: list[str]  # ISO yyyy-mm-dd when determinable, else as shown
    operator: Operator
    product: str
    scam_type: ScamType
    summary: str
    evidence_kinds: list[EvidenceKind]  # one per input image, in order
    tamper_observations: list[str]
    payment_proof_candidate: bool
    # Set by extract_evidence, never by the model, so it is kept out of the JSON schema.
    extraction_failed: SkipJsonSchema[bool] = False
    # True when the summary was blanked for an accusatory term; show a neutral template instead.
    summary_filtered: SkipJsonSchema[bool] = False

    @classmethod
    def failed(cls, image_count: int) -> "Extraction":
        """The partial result returned when the model gave no usable output."""
        return cls(
            phone_numbers=[],
            account_names=[],
            amounts_xaf=[],
            transaction_ids=[],
            dates=[],
            operator="unknown",
            product="",
            scam_type="other",
            summary="",
            evidence_kinds=["other"] * image_count,
            tamper_observations=[],
            payment_proof_candidate=False,
            extraction_failed=True,
        )


class ProductPhoto(BaseModel):
    """Whether a partner-group photo shows a product offered for sale (group listening, F8)."""

    is_product: bool
