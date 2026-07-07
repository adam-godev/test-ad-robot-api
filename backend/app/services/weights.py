from dataclasses import dataclass


def distribute_weights(count: int) -> list[int]:
    if count < 1:
        raise ValueError("At least one offer is required")
    base = 100 // count
    remainder = 100 - base * count
    return [base + (1 if index < remainder else 0) for index in range(count)]


@dataclass(frozen=True)
class OfferWeightInput:
    offer_id: int
    name: str


def with_distributed_weights(offers: list[OfferWeightInput]) -> list[dict[str, int | str]]:
    weights = distribute_weights(len(offers))
    return [
        {"offer_id": offer.offer_id, "name": offer.name, "weight": weights[index]}
        for index, offer in enumerate(offers)
    ]

