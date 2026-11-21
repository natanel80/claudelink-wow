---
name: wow-bags-and-gold
description: Decide what to sell, keep, equip, vendor or put on the auction house in WoW Forever, and how to make gold. Use when the player asks what to do with their bags, what to sell, whether an item is an upgrade, or how to make money.
---

# Bags and gold

## Gather

1. `get_full_report` with `section: "bags"`: every item with count, quality, vendor price (`vendorPrice`, in copper each), auction price (`auctionPrice`, copper each, from Auctionator, with `auctionPriceAgeDays`), and `pawnUpgradePercent` when the Pawn addon thinks it is an upgrade.
2. `get_full_report` with `section: "quests"` to know which items are needed for active quests.
3. `get_live_state` for current money and free bag slots.
4. `get_notes` for things the player decided to keep or collect.

Prices are in copper: 10000 copper = 1 gold, 100 copper = 1 silver.

## Decide, item by item

- **Equip:** items with `pawnUpgradePercent`, if the player meets `requiredLevel`.
- **Keep:** quest items, items needed for the player's professions or notes, ammo, food and drink, potions, bandages.
- **Auction house:** when `auctionPrice` is clearly higher than `vendorPrice` (say more than double, and at least a few silver), and the price is recent (`auctionPriceAgeDays` up to about 7). Mention that the deposit and the 5% cut eat into small sales.
- **Vendor:** grey items (quality 0) and anything not worth the auction house.
- No `auctionPrice` means Auctionator has no recent scan: suggest a scan at the auction house before deciding on valuable items.

## Answer

- Three short lists: equip, sell on the auction house, sell to a vendor. Then anything to keep and why, only if it is not obvious.
- Give totals: about how much gold the vendor sales and the auction sales bring.
- Use the player's language; English item names in backticks.
