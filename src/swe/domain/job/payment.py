# Money for a job (§4.7, SRS Task 7). The system only records what was collected in cash
# or on YOWD's separate card device; it never processes a card or holds card details (A1,
# QA3.8). Payments and adjustments are never edited: a correction is a new adjustment (QA3.5)
import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field, field_validator, model_validator

from swe.domain.shared.base import Record
from swe.domain.shared.errors import DomainError

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Money = Annotated[Decimal, Field(decimal_places=2)]  # AUD (S1)

# a provider reference that looks like a card number is refused, so one can't be stored by mistake
CARD_NUMBER = re.compile(r"\d{13,19}")


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"


# a declined card (Task 7 2a) or a customer who can't or won't pay (3b) is recorded too,
# so the job is flagged for the office rather than closed with no payment
class PaymentOutcome(StrEnum):
    COLLECTED = "collected"
    DECLINED = "declined"
    REFUSED = "refused"


# an optional note left blank on a form counts as not given
def _blank_is_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


# One collection attempt at the job, by the driver in created_by. A job can have several,
# e.g. a declined card then cash, so whether the job is paid is Settlement's decision
class Payment(Record):
    job_id: str
    quote_id: str  # the accepted terms it settles (QA3.4)
    outcome: PaymentOutcome
    method: PaymentMethod | None = None  # None when the customer refused to pay
    amount_due: Money = Field(gt=0)  # what was still owed when this was recorded
    amount: Money = Field(ge=0)  # what was actually collected
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def _reason_given(cls, value: str | None) -> str | None:
        return _blank_is_none(value)

    @model_validator(mode="after")
    def _outcome_is_complete(self) -> "Payment":
        if self.outcome is PaymentOutcome.COLLECTED:
            if self.method is None:
                raise ValueError("a collected payment needs its method")
            if self.amount <= 0:
                raise ValueError("a collected payment needs an amount above zero")
            if self.amount < self.amount_due and not self.reason:
                raise ValueError("a reason is required when less than the amount due is collected (Task 7 3a)")
            return self
        if self.amount != 0:
            raise ValueError(f"a {self.outcome.value} payment collects nothing")
        if not self.reason:
            raise ValueError(f"a {self.outcome.value} payment needs a reason")
        if self.outcome is PaymentOutcome.DECLINED and self.method is not PaymentMethod.CARD:
            raise ValueError("only a card payment can be declined")
        if self.outcome is PaymentOutcome.REFUSED and self.method is not None:
            raise ValueError("a refused payment has no method")
        return self

    # negative for a shortfall. Any variance is surfaced to office staff (QA3.4)
    @computed_field
    @property
    def variance(self) -> Decimal:
        return self.amount - self.amount_due


# A correction or late balance for a Payment, authorised by the office staff member in
# created_by (Task 7 4a). Negative to correct an amount recorded too high
class PaymentAdjustment(Record):
    job_id: str
    payment_id: str  # the Payment it adjusts
    amount: Money
    method: PaymentMethod
    provider_reference: str | None = Field(default=None, max_length=200)  # the card device's approval reference
    reason: Text

    @field_validator("provider_reference", mode="before")
    @classmethod
    def _reference_given(cls, value: str | None) -> str | None:
        return _blank_is_none(value)

    @model_validator(mode="after")
    def _adjustment_is_complete(self) -> "PaymentAdjustment":
        if self.amount == 0:
            raise ValueError("an adjustment needs a non-zero amount")
        if self.method is PaymentMethod.CARD and not self.provider_reference:
            raise ValueError("a card adjustment needs the payment device's reference")
        if self.provider_reference and CARD_NUMBER.search(self.provider_reference.replace(" ", "")):
            raise ValueError("enter the device's approval reference, never a card number (QA3.8)")
        return self


# What a job owes and what has been collected towards it, across all its Payments and
# PaymentAdjustments. It decides whether the payment is resolved, which Delivered needs
# before the job can close (A18, Task 7 3b). Stored once per job so concurrent payments
# lock on its revision
class Settlement(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    job_id: str = Field(frozen=True)
    amount_due: Decimal = Field(gt=0, frozen=True)  # the accepted quote's price
    net_collected: Decimal = Decimal(0)
    revision: int = Field(default=0, ge=0)  # 0 until first saved; never goes back, so the repo locks on it

    # negative when more was collected than was due
    @computed_field
    @property
    def outstanding(self) -> Decimal:
        return self.amount_due - self.net_collected

    @computed_field
    @property
    def resolved(self) -> bool:
        return self.outstanding == 0

    # what the next Payment should collect; refused once nothing more is owed
    def due(self) -> Decimal:
        if self.resolved:
            raise DomainError("this job's payment is already resolved")
        if self.outstanding < 0:
            raise DomainError("more than the amount due has been collected; office staff must correct it")
        return self.outstanding

    def apply_payment(self, payment: Payment) -> None:
        self.due()
        self._add(payment.amount)

    # allowed after resolution too, since an error can be found later (Task 7 4a); the
    # job's state refuses it once closed
    def apply_adjustment(self, adjustment: PaymentAdjustment) -> None:
        if self.net_collected + adjustment.amount < 0:
            raise DomainError("an adjustment can't take the amount collected below zero")
        self._add(adjustment.amount)

    def _add(self, amount: Decimal) -> None:
        self.net_collected += amount
        self.revision += 1
