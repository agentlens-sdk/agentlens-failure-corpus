"""Family B: tool-use tasks against deterministic mock APIs.

Shape borrowed from tau-bench: a small domain API (retail, airline, ops, calendar) plus many
scenarios over it. Each scenario fixes a prompt, a written policy in the system prompt, and a
checker that reads final state and the tool-call log. No LLM judges: every check is a
state/equality assertion, so a trace's pass/fail never drifts between nights.

Every task carries `solution`, a hand-written correct tool sequence, exercised by tests/test_tasks.py.
"""
import copy
import json

from .base import Task


def T(name, desc, **props):
    """Compact tool schema. A property named `foo_opt` becomes optional property `foo`."""
    schema, req = {}, []
    for k, v in props.items():
        optional = k.endswith("_opt")
        key = k[:-4] if optional else k
        schema[key] = {"type": v}
        if not optional:
            req.append(key)
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": schema, "required": req}}


def J(x):
    return json.dumps(x)


class Mock(Task):
    """Base for every Family B task: fixture deepcopy per episode, tool-call log, dispatch by name."""
    family = "tools"
    FIXTURE = {}

    def __init__(self):
        self.db = copy.deepcopy(self.FIXTURE)
        self.calls = []

    def execute(self, name, inp):
        self.calls.append((name, dict(inp)))
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            return "unknown tool"
        try:
            return fn(**inp)
        except TypeError as e:
            return f"bad arguments: {e}"

    # -- checker helpers -------------------------------------------------
    def did(self, name):
        """Every input dict passed to `name`, in call order."""
        return [i for n, i in self.calls if n == name]

    def never(self, *names):
        return not any(n in names for n, _ in self.calls)

    def messaged(self, to=None, contains=()):
        for m in self.did("send_message"):
            if to is not None and str(m.get("user_id", m.get("to", ""))) != str(to):
                continue
            text = str(m.get("text", "")).lower()
            if all(str(s).lower() in text for s in contains):
                return True
        return False


# ======================================================================
# Retail / support domain
# ======================================================================
RETAIL_POLICY = """You are a retail support agent. Follow this policy exactly.
- Never act on an order you have not fetched with get_order first.
- Refunds: delivered orders only, and only the lines the customer names. Never refund a whole order
  unless every line is affected.
- Cancellation: only while the order status is 'pending'. Shipped or delivered orders cannot be cancelled.
- Address changes: only while the order status is 'pending'.
- Exchanges: only for a SKU that is in stock (stock > 0).
- Discounts: gold members only, and never more than 10 percent.
- When you cannot do what was asked, do not do something else instead: explain with send_message.
- Always finish by confirming to the customer with send_message."""

RETAIL_TOOLS = [
    T("get_user", "Fetch a customer record including membership tier", user_id="string"),
    T("get_order", "Fetch one order by id", order_id="string"),
    T("list_orders", "List a customer's orders, newest last", user_id="string"),
    T("get_product", "Fetch a product including stock level", sku="string"),
    T("cancel_order", "Cancel a pending order", order_id="string", reason="string"),
    T("refund_line", "Refund one line of a delivered order", order_id="string", sku="string", qty_opt="integer"),
    T("exchange_line", "Exchange one line for another SKU", order_id="string", sku="string", new_sku="string"),
    T("update_address", "Change the shipping address of a pending order", order_id="string", line1="string", city="string", zip="string"),
    T("apply_discount", "Apply a percentage discount to an order", order_id="string", percent="number"),
    T("send_message", "Send a message to the customer", user_id="string", text="string"),
]

RETAIL_FIXTURE = {
    "users": {
        "4412": {"user_id": "4412", "name": "Dana Osei", "tier": "gold", "address": {"line1": "12 Alder St", "city": "Portland", "zip": "97201"}},
        "5501": {"user_id": "5501", "name": "Ravi Menon", "tier": "basic", "address": {"line1": "88 Kite Rd", "city": "Austin", "zip": "78701"}},
        "6620": {"user_id": "6620", "name": "Sam Iyer", "tier": "silver", "address": {"line1": "5 Bay Ct", "city": "Oakland", "zip": "94607"}},
    },
    "orders": {
        "O-9001": {"order_id": "O-9001", "user_id": "4412", "status": "delivered", "placed": "2026-08-01",
                   "lines": [{"sku": "SKU-12", "name": "Desk lamp", "price": 40.0, "qty": 1},
                             {"sku": "SKU-77", "name": "Ceramic mug", "price": 25.0, "qty": 2}]},
        "O-9002": {"order_id": "O-9002", "user_id": "4412", "status": "pending", "placed": "2026-08-20",
                   "lines": [{"sku": "SKU-31", "name": "Wool throw, grey", "price": 90.0, "qty": 1}]},
        "O-9003": {"order_id": "O-9003", "user_id": "5501", "status": "shipped", "placed": "2026-08-18",
                   "lines": [{"sku": "SKU-12", "name": "Desk lamp", "price": 40.0, "qty": 1}]},
        "O-9004": {"order_id": "O-9004", "user_id": "6620", "status": "delivered", "placed": "2026-07-02",
                   "lines": [{"sku": "SKU-55", "name": "Chef knife", "price": 120.0, "qty": 1}]},
        "O-9005": {"order_id": "O-9005", "user_id": "6620", "status": "delivered", "placed": "2026-08-25",
                   "lines": [{"sku": "SKU-77", "name": "Ceramic mug", "price": 25.0, "qty": 1},
                             {"sku": "SKU-12", "name": "Desk lamp", "price": 40.0, "qty": 1}]},
        "O-9006": {"order_id": "O-9006", "user_id": "5501", "status": "delivered", "placed": "2026-08-11",
                   "lines": [{"sku": "SKU-31", "name": "Wool throw, grey", "price": 90.0, "qty": 1},
                             {"sku": "SKU-55", "name": "Chef knife", "price": 120.0, "qty": 1}]},
        "O-9007": {"order_id": "O-9007", "user_id": "4412", "status": "pending", "placed": "2026-08-28",
                   "lines": [{"sku": "SKU-55", "name": "Chef knife", "price": 120.0, "qty": 1}]},
    },
    "products": {
        "SKU-12": {"sku": "SKU-12", "name": "Desk lamp", "price": 40.0, "stock": 7},
        "SKU-31": {"sku": "SKU-31", "name": "Wool throw, grey", "price": 90.0, "stock": 2},
        "SKU-32": {"sku": "SKU-32", "name": "Wool throw, oat", "price": 90.0, "stock": 4},
        "SKU-33": {"sku": "SKU-33", "name": "Wool throw, indigo", "price": 90.0, "stock": 0},
        "SKU-55": {"sku": "SKU-55", "name": "Chef knife", "price": 120.0, "stock": 1},
        "SKU-77": {"sku": "SKU-77", "name": "Ceramic mug", "price": 25.0, "stock": 12},
    },
}


class Retail(Mock):
    system = RETAIL_POLICY
    tools = RETAIL_TOOLS
    FIXTURE = RETAIL_FIXTURE

    def t_get_user(self, user_id):
        return J(self.db["users"].get(user_id) or {"error": "no such user"})

    def t_get_order(self, order_id):
        return J(self.db["orders"].get(order_id) or {"error": "no such order"})

    def t_list_orders(self, user_id):
        rows = [o for o in self.db["orders"].values() if o["user_id"] == user_id]
        return J([{"order_id": o["order_id"], "status": o["status"], "placed": o["placed"]}
                  for o in sorted(rows, key=lambda o: o["placed"])])

    def t_get_product(self, sku):
        return J(self.db["products"].get(sku) or {"error": "no such product"})

    def t_cancel_order(self, order_id, reason):
        o = self.db["orders"].get(order_id)
        if not o:
            return "error: no such order"
        if o["status"] != "pending":
            return f"error: cannot cancel an order with status {o['status']}"
        o["status"] = "cancelled"
        o["cancel_reason"] = reason
        return "cancelled"

    def t_refund_line(self, order_id, sku, qty=None):
        o = self.db["orders"].get(order_id)
        if not o:
            return "error: no such order"
        if o["status"] != "delivered":
            return f"error: cannot refund an order with status {o['status']}"
        line = next((l for l in o["lines"] if l["sku"] == sku), None)
        if not line:
            return "error: that sku is not on this order"
        n = line["qty"] if qty is None else int(qty)
        if n < 1 or n > line["qty"]:
            return f"error: this order has {line['qty']} of {sku}"
        o.setdefault("refunds", []).append({"sku": sku, "qty": n, "amount": round(line["price"] * n, 2)})
        return J({"refunded": round(line["price"] * n, 2), "sku": sku, "qty": n})

    def t_exchange_line(self, order_id, sku, new_sku):
        o = self.db["orders"].get(order_id)
        p = self.db["products"].get(new_sku)
        if not o or not p:
            return "error: no such order or product"
        if p["stock"] < 1:
            return f"error: {new_sku} is out of stock"
        line = next((l for l in o["lines"] if l["sku"] == sku), None)
        if not line:
            return "error: that sku is not on this order"
        o.setdefault("exchanges", []).append({"from": sku, "to": new_sku})
        line["sku"] = new_sku
        p["stock"] -= 1
        return "exchanged"

    def t_update_address(self, order_id, line1, city, zip):
        o = self.db["orders"].get(order_id)
        if not o:
            return "error: no such order"
        if o["status"] != "pending":
            return f"error: cannot change the address of a {o['status']} order"
        o["address"] = {"line1": line1, "city": city, "zip": zip}
        return "address updated"

    def t_apply_discount(self, order_id, percent):
        o = self.db["orders"].get(order_id)
        if not o:
            return "error: no such order"
        o.setdefault("discounts", []).append(float(percent))
        return f"applied {percent}%"

    def t_send_message(self, user_id, text):
        return "sent"

    # convenience for checkers
    def order(self, oid):
        return self.db["orders"][oid]

    def refunds(self, oid):
        return [(r["sku"], r["qty"]) for r in self.db["orders"][oid].get("refunds", [])]


# -- retail scenarios --------------------------------------------------
class RefundBrokenLine(Retail):
    task_id = "retail_refund_line"
    prompt = ("Customer 4412 says both ceramic mugs (SKU-77) on order O-9001 arrived broken. "
              "Refund only that line, then confirm to the customer.")
    solution = [("get_order", {"order_id": "O-9001"}),
                ("refund_line", {"order_id": "O-9001", "sku": "SKU-77", "qty": 2}),
                ("send_message", {"user_id": "4412", "text": "Refunded both mugs."})]
    def check(self):
        return self.refunds("O-9001") == [("SKU-77", 2)] and self.messaged("4412")


class RefundPendingOrder(Retail):
    task_id = "retail_refund_pending_is_cancel"
    prompt = ("Customer 4412 changed their mind about order O-9002 and wants their money back. "
              "Do whatever the policy allows and tell them what you did.")
    solution = [("get_order", {"order_id": "O-9002"}),
                ("cancel_order", {"order_id": "O-9002", "reason": "customer changed their mind"}),
                ("send_message", {"user_id": "4412", "text": "Cancelled before shipping, no charge."})]
    def check(self):
        return (self.order("O-9002")["status"] == "cancelled"
                and self.never("refund_line") and self.messaged("4412"))


class CancelPending(Retail):
    task_id = "retail_cancel_pending"
    prompt = "Customer 4412 wants to cancel order O-9007. Handle it and confirm."
    solution = [("get_order", {"order_id": "O-9007"}),
                ("cancel_order", {"order_id": "O-9007", "reason": "customer request"}),
                ("send_message", {"user_id": "4412", "text": "Order O-9007 is cancelled."})]
    def check(self):
        return self.order("O-9007")["status"] == "cancelled" and self.messaged("4412")


class CancelShippedRefuses(Retail):
    task_id = "retail_cancel_shipped_refuses"
    prompt = "Customer 5501 wants to cancel order O-9003. Handle it and confirm."
    solution = [("get_order", {"order_id": "O-9003"}),
                ("send_message", {"user_id": "5501", "text": "O-9003 has already shipped, so it cannot be cancelled."})]
    def check(self):
        return (self.order("O-9003")["status"] == "shipped"
                and self.never("cancel_order") and self.messaged("5501"))


class AddressChangePending(Retail):
    task_id = "retail_address_change_pending"
    prompt = ("Customer 4412 asks to ship order O-9007 to 44 Pine Ave, Portland, 97209 instead. "
              "Update it and confirm.")
    solution = [("get_order", {"order_id": "O-9007"}),
                ("update_address", {"order_id": "O-9007", "line1": "44 Pine Ave", "city": "Portland", "zip": "97209"}),
                ("send_message", {"user_id": "4412", "text": "Address updated."})]
    def check(self):
        return (self.order("O-9007").get("address") == {"line1": "44 Pine Ave", "city": "Portland", "zip": "97209"}
                and self.messaged("4412"))


class AddressChangeShippedRefuses(Retail):
    task_id = "retail_address_change_shipped_refuses"
    prompt = "Customer 5501 asks to redirect order O-9003 to 90 Cedar Way, Austin, 78702. Handle it and confirm."
    solution = [("get_order", {"order_id": "O-9003"}),
                ("send_message", {"user_id": "5501", "text": "O-9003 has shipped, the address can no longer be changed."})]
    def check(self):
        return ("address" not in self.order("O-9003")
                and self.never("update_address") and self.messaged("5501"))


class ExchangeInStock(Retail):
    task_id = "retail_exchange_in_stock"
    prompt = ("Customer 4412 wants the wool throw on order O-9002 in oat (SKU-32) instead of grey. "
              "Make the exchange if you can and confirm.")
    solution = [("get_order", {"order_id": "O-9002"}),
                ("get_product", {"sku": "SKU-32"}),
                ("exchange_line", {"order_id": "O-9002", "sku": "SKU-31", "new_sku": "SKU-32"}),
                ("send_message", {"user_id": "4412", "text": "Swapped to the oat throw."})]
    def check(self):
        return (self.order("O-9002").get("exchanges") == [{"from": "SKU-31", "to": "SKU-32"}]
                and self.messaged("4412"))


class ExchangeOutOfStock(Retail):
    task_id = "retail_exchange_out_of_stock"
    prompt = ("Customer 4412 wants the wool throw on order O-9002 in indigo (SKU-33) instead of grey. "
              "Make the exchange if you can and confirm.")
    solution = [("get_order", {"order_id": "O-9002"}),
                ("get_product", {"sku": "SKU-33"}),
                ("send_message", {"user_id": "4412", "text": "The indigo throw is out of stock, so I left the order as is."})]
    def check(self):
        return (not self.order("O-9002").get("exchanges")
                and self.never("exchange_line") and self.messaged("4412"))


class DiscountGoldMax(Retail):
    task_id = "retail_discount_gold_max"
    prompt = ("Customer 4412 has complained about a late delivery and asks for the largest goodwill "
              "discount you are allowed to give on order O-9007. Apply it and confirm.")
    solution = [("get_user", {"user_id": "4412"}),
                ("get_order", {"order_id": "O-9007"}),
                ("apply_discount", {"order_id": "O-9007", "percent": 10}),
                ("send_message", {"user_id": "4412", "text": "Applied a 10% discount."})]
    def check(self):
        return self.order("O-9007").get("discounts") == [10.0] and self.messaged("4412")


class DiscountBasicRefuses(Retail):
    task_id = "retail_discount_basic_refuses"
    prompt = "Customer 5501 asks for a goodwill discount on order O-9006. Handle it and confirm."
    solution = [("get_user", {"user_id": "5501"}),
                ("send_message", {"user_id": "5501", "text": "Goodwill discounts are limited to gold members."})]
    def check(self):
        return (not self.order("O-9006").get("discounts")
                and self.never("apply_discount") and self.messaged("5501"))


class DiscountCap(Retail):
    task_id = "retail_discount_cap"
    prompt = "Customer 4412 demands 25 percent off order O-9007. Do what the policy allows and confirm."
    solution = [("get_user", {"user_id": "4412"}),
                ("apply_discount", {"order_id": "O-9007", "percent": 10}),
                ("send_message", {"user_id": "4412", "text": "10% is the most I can apply."})]
    def check(self):
        return self.order("O-9007").get("discounts") == [10.0] and self.messaged("4412")


class RefundWholeOrder(Retail):
    task_id = "retail_refund_all_lines"
    prompt = ("Customer 6620 says the box for order O-9005 was crushed and everything inside is broken. "
              "Refund what is appropriate and confirm.")
    solution = [("get_order", {"order_id": "O-9005"}),
                ("refund_line", {"order_id": "O-9005", "sku": "SKU-77"}),
                ("refund_line", {"order_id": "O-9005", "sku": "SKU-12"}),
                ("send_message", {"user_id": "6620", "text": "Refunded the full order."})]
    def check(self):
        return (sorted(self.refunds("O-9005")) == [("SKU-12", 1), ("SKU-77", 1)]
                and self.messaged("6620"))


class LatestOrderRefund(Retail):
    task_id = "retail_latest_order_refund"
    prompt = ("Customer 6620 says the mug from their most recent order arrived cracked. "
              "Refund it and confirm. They did not give an order number.")
    solution = [("list_orders", {"user_id": "6620"}),
                ("get_order", {"order_id": "O-9005"}),
                ("refund_line", {"order_id": "O-9005", "sku": "SKU-77"}),
                ("send_message", {"user_id": "6620", "text": "Refunded the mug from O-9005."})]
    def check(self):
        return (self.refunds("O-9005") == [("SKU-77", 1)]
                and not self.refunds("O-9004") and self.messaged("6620"))


class PartialQtyRefund(Retail):
    task_id = "retail_partial_qty_refund"
    prompt = ("Customer 4412 ordered two ceramic mugs on O-9001 and says exactly one of them is broken. "
              "Refund what is owed and confirm.")
    solution = [("get_order", {"order_id": "O-9001"}),
                ("refund_line", {"order_id": "O-9001", "sku": "SKU-77", "qty": 1}),
                ("send_message", {"user_id": "4412", "text": "Refunded one mug."})]
    def check(self):
        return self.refunds("O-9001") == [("SKU-77", 1)] and self.messaged("4412")


class MissingOrder(Retail):
    task_id = "retail_missing_order"
    prompt = "Customer 5501 asks you to refund order O-9999. Handle it and confirm."
    solution = [("get_order", {"order_id": "O-9999"}),
                ("send_message", {"user_id": "5501", "text": "I cannot find an order O-9999 on your account."})]
    def check(self):
        return (self.did("get_order")
                and self.never("refund_line", "cancel_order", "exchange_line", "update_address", "apply_discount")
                and self.messaged("5501"))


class RefundAmountStated(Retail):
    task_id = "retail_refund_amount_stated"
    prompt = ("Customer 5501 says the chef knife on order O-9006 was delivered with a chipped blade. "
              "Refund that line and tell the customer the exact refund amount in dollars.")
    solution = [("get_order", {"order_id": "O-9006"}),
                ("refund_line", {"order_id": "O-9006", "sku": "SKU-55"}),
                ("send_message", {"user_id": "5501", "text": "Refunded $120.00 for the chef knife."})]
    def check(self):
        return self.refunds("O-9006") == [("SKU-55", 1)] and self.messaged("5501", contains=["120"])


# -- retail, compositional ---------------------------------------------
# Added after the first live run: the single-step scenarios above were passed 18/18 by Sonnet 5,
# which yields almost no failures to label. These need several dependent lookups, a filter, or
# arithmetic carried into the reply.
class CancelWhatYouCan(Retail):
    task_id = "retail_cancel_what_you_can"
    prompt = ("Customer 4412 wants to cancel everything they still have outstanding. Cancel what the "
              "policy allows and tell them exactly which of their orders you could not cancel.")
    solution = [("list_orders", {"user_id": "4412"}),
                ("get_order", {"order_id": "O-9002"}),
                ("cancel_order", {"order_id": "O-9002", "reason": "customer request"}),
                ("get_order", {"order_id": "O-9007"}),
                ("cancel_order", {"order_id": "O-9007", "reason": "customer request"}),
                ("get_order", {"order_id": "O-9001"}),
                ("send_message", {"user_id": "4412", "text": "Cancelled O-9002 and O-9007. O-9001 was already delivered, so it cannot be cancelled."})]
    def check(self):
        return (self.order("O-9002")["status"] == "cancelled"
                and self.order("O-9007")["status"] == "cancelled"
                and self.order("O-9001")["status"] == "delivered"
                and self.messaged("4412", contains=["O-9001"]))


class ThresholdRefund(Retail):
    task_id = "retail_threshold_refund"
    prompt = ("Customer 5501 reports water damage in storage. Refund every line over $50 on their "
              "delivered orders only, then tell them the exact total refunded in dollars.")
    solution = [("list_orders", {"user_id": "5501"}),
                ("get_order", {"order_id": "O-9006"}),
                ("get_order", {"order_id": "O-9003"}),
                ("refund_line", {"order_id": "O-9006", "sku": "SKU-31"}),
                ("refund_line", {"order_id": "O-9006", "sku": "SKU-55"}),
                ("send_message", {"user_id": "5501", "text": "Refunded $210.00 across order O-9006."})]
    def check(self):
        return (sorted(self.refunds("O-9006")) == [("SKU-31", 1), ("SKU-55", 1)]
                and not self.refunds("O-9003") and self.messaged("5501", contains=["210"]))


class MostExpensiveEver(Retail):
    task_id = "retail_most_expensive_ever"
    prompt = ("Refund the single most expensive item customer 6620 has ever received, and tell them "
              "which order it was on.")
    solution = [("list_orders", {"user_id": "6620"}),
                ("get_order", {"order_id": "O-9004"}),
                ("get_order", {"order_id": "O-9005"}),
                ("refund_line", {"order_id": "O-9004", "sku": "SKU-55"}),
                ("send_message", {"user_id": "6620", "text": "Refunded the chef knife from order O-9004."})]
    def check(self):
        return (self.refunds("O-9004") == [("SKU-55", 1)] and not self.refunds("O-9005")
                and self.messaged("6620", contains=["O-9004"]))


class AddressPlusCappedDiscount(Retail):
    task_id = "retail_address_plus_capped_discount"
    prompt = ("Customer 4412 wants order O-9002 shipped to 7 Larch Way, Portland, 97210 and a 20 percent "
              "discount for the trouble. Do everything the policy allows and explain anything you could not do.")
    solution = [("get_order", {"order_id": "O-9002"}),
                ("get_user", {"user_id": "4412"}),
                ("update_address", {"order_id": "O-9002", "line1": "7 Larch Way", "city": "Portland", "zip": "97210"}),
                ("apply_discount", {"order_id": "O-9002", "percent": 10}),
                ("send_message", {"user_id": "4412", "text": "Address updated and a 10% discount applied; 10% is the maximum."})]
    def check(self):
        return (self.order("O-9002").get("address") == {"line1": "7 Larch Way", "city": "Portland", "zip": "97210"}
                and self.order("O-9002").get("discounts") == [10.0] and self.messaged("4412"))


class ExchangeWhicheverShips(Retail):
    task_id = "retail_exchange_whichever_ships"
    prompt = ("Customer 4412 wants the wool throw on order O-9002 in a different colour, whichever one "
              "you can actually ship today. Make the exchange and tell them the colour.")
    solution = [("get_order", {"order_id": "O-9002"}),
                ("get_product", {"sku": "SKU-32"}),
                ("get_product", {"sku": "SKU-33"}),
                ("exchange_line", {"order_id": "O-9002", "sku": "SKU-31", "new_sku": "SKU-32"}),
                ("send_message", {"user_id": "4412", "text": "Swapped to the oat throw, the indigo one is out of stock."})]
    def check(self):
        return (self.order("O-9002").get("exchanges") == [{"from": "SKU-31", "to": "SKU-32"}]
                and self.messaged("4412"))


class NothingWarranted(Retail):
    task_id = "retail_nothing_warranted"
    prompt = ("Customer 5501 is annoyed that order O-9003 is taking so long. They have not asked for "
              "anything specific. Do whatever the policy allows and reply to them.")
    solution = [("get_order", {"order_id": "O-9003"}),
                ("get_user", {"user_id": "5501"}),
                ("send_message", {"user_id": "5501", "text": "O-9003 has shipped and is on its way; I cannot cancel or discount it."})]
    def check(self):
        return (self.never("refund_line", "cancel_order", "exchange_line", "update_address", "apply_discount")
                and self.messaged("5501"))


# ======================================================================
# Airline domain
# ======================================================================
AIR_POLICY = """You are an airline service agent. Today is 2026-09-06. Follow this policy exactly.
- Never change or cancel a reservation you have not fetched with get_reservation first.
- Basic economy reservations cannot be changed and cannot be upgraded. They may be cancelled only
  within 24 hours of booking.
- Never put a passenger on a flight that did not come back from search_flights.
- Checked bags: gold members get one free checked bag; everyone else pays. Maximum 2 per passenger.
- If the airline cancelled the flight, the passenger cancels free of charge (free=true).
- When the policy forbids what was asked, do not do something else instead: explain with send_message.
- Always finish by confirming to the passenger with send_message."""

AIR_TOOLS = [
    T("get_reservation", "Fetch a reservation", reservation_id="string"),
    T("get_user", "Fetch a passenger record including membership tier", user_id="string"),
    T("search_flights", "Search bookable flights", origin="string", dest="string", date="string"),
    T("change_flight", "Move a reservation onto another flight", reservation_id="string", flight="string"),
    T("add_baggage", "Add checked bags", reservation_id="string", count="integer", paid="boolean"),
    T("upgrade_cabin", "Upgrade the cabin", reservation_id="string", cabin="string"),
    T("cancel_reservation", "Cancel a reservation", reservation_id="string", free="boolean"),
    T("get_policy", "Read a policy section: baggage, changes, cancellation, upgrades", topic="string"),
    T("send_message", "Send a message to the passenger", user_id="string", text="string"),
]

AIR_FIXTURE = {
    "users": {
        "4412": {"user_id": "4412", "name": "Dana Osei", "tier": "gold"},
        "5501": {"user_id": "5501", "name": "Ravi Menon", "tier": "basic"},
        "6620": {"user_id": "6620", "name": "Sam Iyer", "tier": "silver"},
    },
    "reservations": {
        "R-1001": {"reservation_id": "R-1001", "user_id": "4412", "fare": "basic_economy", "cabin": "economy",
                   "flight": "AL120", "origin": "LAX", "dest": "JFK", "date": "2026-09-20",
                   "booked": "2026-08-01", "status": "confirmed", "bags": 0},
        "R-1002": {"reservation_id": "R-1002", "user_id": "6620", "fare": "economy", "cabin": "economy",
                   "flight": "AL220", "origin": "SFO", "dest": "ORD", "date": "2026-09-25",
                   "booked": "2026-08-10", "status": "confirmed", "bags": 0},
        "R-1003": {"reservation_id": "R-1003", "user_id": "5501", "fare": "economy", "cabin": "economy",
                   "flight": "AL330", "origin": "SEA", "dest": "DEN", "date": "2026-09-12",
                   "booked": "2026-08-15", "status": "cancelled_by_airline", "bags": 1},
        "R-1004": {"reservation_id": "R-1004", "user_id": "4412", "fare": "business", "cabin": "business",
                   "flight": "AL410", "origin": "JFK", "dest": "LHR", "date": "2026-10-02",
                   "booked": "2026-09-06", "status": "confirmed", "bags": 0},
        "R-1005": {"reservation_id": "R-1005", "user_id": "6620", "fare": "basic_economy", "cabin": "economy",
                   "flight": "AL510", "origin": "LAX", "dest": "SEA", "date": "2026-11-14",
                   "booked": "2026-09-06", "status": "confirmed", "bags": 0},
    },
    "flights": {
        ("LAX", "JFK", "2026-09-21"): [{"flight": "AL122", "depart": "06:15"}, {"flight": "AL124", "depart": "13:40"}],
        ("SFO", "ORD", "2026-09-25"): [{"flight": "AL222", "depart": "09:00"}, {"flight": "AL224", "depart": "12:45"},
                                       {"flight": "AL226", "depart": "18:10"}],
        ("SEA", "DEN", "2026-09-12"): [{"flight": "AL332", "depart": "11:00"}, {"flight": "AL334", "depart": "17:45"}],
    },
}

AIR_POLICY_TEXT = {
    "baggage": "Gold members receive one free checked bag. All other tiers pay for every checked bag. Maximum 2 per passenger.",
    "changes": "Basic economy reservations cannot be changed. All other fares may be changed to any flight returned by search_flights.",
    "cancellation": "Basic economy may be cancelled only within 24 hours of booking, free of charge. If the airline cancelled the flight, cancellation is always free.",
    "upgrades": "Basic economy cannot be upgraded. Other fares may upgrade to any higher cabin.",
}


class Airline(Mock):
    system = AIR_POLICY
    tools = AIR_TOOLS
    FIXTURE = AIR_FIXTURE

    def t_get_reservation(self, reservation_id):
        return J(self.db["reservations"].get(reservation_id) or {"error": "no such reservation"})

    def t_get_user(self, user_id):
        return J(self.db["users"].get(user_id) or {"error": "no such user"})

    def t_get_policy(self, topic):
        return AIR_POLICY_TEXT.get(topic.strip().lower(), "no such policy section")

    def t_search_flights(self, origin, dest, date):
        return J(self.db["flights"].get((origin.upper(), dest.upper(), date), []))

    def t_change_flight(self, reservation_id, flight):
        r = self.db["reservations"].get(reservation_id)
        if not r:
            return "error: no such reservation"
        if r["fare"] == "basic_economy":
            return "error: basic economy reservations cannot be changed"
        if not any(f["flight"] == flight for fl in self.db["flights"].values() for f in fl):
            return f"error: {flight} is not a bookable flight"
        r["flight"] = flight
        return "changed"

    def t_add_baggage(self, reservation_id, count, paid):
        r = self.db["reservations"].get(reservation_id)
        if not r:
            return "error: no such reservation"
        if r["bags"] + int(count) > 2:
            return f"error: maximum 2 checked bags, this reservation has {r['bags']}"
        r["bags"] += int(count)
        r.setdefault("baggage", []).append({"count": int(count), "paid": bool(paid)})
        return J({"bags": r["bags"], "paid": bool(paid)})

    def t_upgrade_cabin(self, reservation_id, cabin):
        r = self.db["reservations"].get(reservation_id)
        if not r:
            return "error: no such reservation"
        if r["fare"] == "basic_economy":
            return "error: basic economy cannot be upgraded"
        r["cabin"] = cabin.strip().lower()
        return "upgraded"

    def t_cancel_reservation(self, reservation_id, free):
        r = self.db["reservations"].get(reservation_id)
        if not r:
            return "error: no such reservation"
        r["status"] = "cancelled"
        r["cancelled_free"] = bool(free)
        return "cancelled"

    def t_send_message(self, user_id, text):
        return "sent"

    def res(self, rid):
        return self.db["reservations"][rid]


class AirChangeFlexible(Airline):
    task_id = "air_change_flexible"
    prompt = ("Passenger 6620 (reservation R-1002) wants the last SFO to ORD flight on 2026-09-25 instead. "
              "Move them and confirm.")
    solution = [("get_reservation", {"reservation_id": "R-1002"}),
                ("search_flights", {"origin": "SFO", "dest": "ORD", "date": "2026-09-25"}),
                ("change_flight", {"reservation_id": "R-1002", "flight": "AL226"}),
                ("send_message", {"user_id": "6620", "text": "Moved you to AL226, departing 18:10."})]
    def check(self):
        return self.res("R-1002")["flight"] == "AL226" and self.messaged("6620")


class AirChangeBasicRefuses(Airline):
    task_id = "air_change_basic_refuses"
    prompt = ("Passenger 4412 (reservation R-1001) wants to fly LAX to JFK on 2026-09-21 instead of 2026-09-20. "
              "Handle it and confirm.")
    solution = [("get_reservation", {"reservation_id": "R-1001"}),
                ("get_policy", {"topic": "changes"}),
                ("send_message", {"user_id": "4412", "text": "R-1001 is basic economy, which cannot be changed."})]
    def check(self):
        return (self.res("R-1001")["flight"] == "AL120"
                and self.never("change_flight") and self.messaged("4412"))


class AirCancelAirlineCancelled(Airline):
    task_id = "air_cancel_airline_cancelled_free"
    prompt = ("Passenger 5501 heard their flight on reservation R-1003 was cancelled by the airline and "
              "does not want to rebook. Cancel it and confirm.")
    solution = [("get_reservation", {"reservation_id": "R-1003"}),
                ("get_policy", {"topic": "cancellation"}),
                ("cancel_reservation", {"reservation_id": "R-1003", "free": True}),
                ("send_message", {"user_id": "5501", "text": "Cancelled at no charge, full refund."})]
    def check(self):
        r = self.res("R-1003")
        return r["status"] == "cancelled" and r.get("cancelled_free") is True and self.messaged("5501")


class AirBagFreeGold(Airline):
    task_id = "air_bag_free_gold"
    prompt = "Passenger 4412 wants to add one checked bag to reservation R-1004. Add it and confirm, saying whether it costs anything."
    solution = [("get_reservation", {"reservation_id": "R-1004"}),
                ("get_user", {"user_id": "4412"}),
                ("get_policy", {"topic": "baggage"}),
                ("add_baggage", {"reservation_id": "R-1004", "count": 1, "paid": False}),
                ("send_message", {"user_id": "4412", "text": "Added, free with your gold membership."})]
    def check(self):
        return self.res("R-1004").get("baggage") == [{"count": 1, "paid": False}] and self.messaged("4412")


class AirBagPaidSilver(Airline):
    task_id = "air_bag_paid_silver"
    prompt = "Passenger 6620 wants to add one checked bag to reservation R-1002. Add it and confirm, saying whether it costs anything."
    solution = [("get_reservation", {"reservation_id": "R-1002"}),
                ("get_user", {"user_id": "6620"}),
                ("get_policy", {"topic": "baggage"}),
                ("add_baggage", {"reservation_id": "R-1002", "count": 1, "paid": True}),
                ("send_message", {"user_id": "6620", "text": "Added as a paid checked bag."})]
    def check(self):
        return self.res("R-1002").get("baggage") == [{"count": 1, "paid": True}] and self.messaged("6620")


class AirUpgradeOk(Airline):
    task_id = "air_upgrade_ok"
    prompt = "Passenger 6620 wants reservation R-1002 upgraded to business. Handle it and confirm."
    solution = [("get_reservation", {"reservation_id": "R-1002"}),
                ("upgrade_cabin", {"reservation_id": "R-1002", "cabin": "business"}),
                ("send_message", {"user_id": "6620", "text": "You are in business class now."})]
    def check(self):
        return self.res("R-1002")["cabin"] == "business" and self.messaged("6620")


class AirUpgradeBasicRefuses(Airline):
    task_id = "air_upgrade_basic_refuses"
    prompt = "Passenger 4412 wants reservation R-1001 upgraded to business. Handle it and confirm."
    solution = [("get_reservation", {"reservation_id": "R-1001"}),
                ("get_policy", {"topic": "upgrades"}),
                ("send_message", {"user_id": "4412", "text": "Basic economy cannot be upgraded."})]
    def check(self):
        return (self.res("R-1001")["cabin"] == "economy"
                and self.never("upgrade_cabin") and self.messaged("4412"))


class AirRebookEarliestAfternoon(Airline):
    task_id = "air_rebook_earliest_after_noon"
    prompt = ("Passenger 6620 (reservation R-1002) has a morning meeting and needs the earliest SFO to ORD "
              "flight on 2026-09-25 that departs after 12:00. Move them and tell them the flight number.")
    solution = [("get_reservation", {"reservation_id": "R-1002"}),
                ("search_flights", {"origin": "SFO", "dest": "ORD", "date": "2026-09-25"}),
                ("change_flight", {"reservation_id": "R-1002", "flight": "AL224"}),
                ("send_message", {"user_id": "6620", "text": "You are on AL224 at 12:45."})]
    def check(self):
        return self.res("R-1002")["flight"] == "AL224" and self.messaged("6620", contains=["AL224"])


class AirCancelWithin24h(Airline):
    task_id = "air_cancel_basic_within_24h"
    prompt = ("Passenger 6620 booked reservation R-1005 today and wants to cancel it. "
              "Do what the policy allows and confirm.")
    solution = [("get_reservation", {"reservation_id": "R-1005"}),
                ("get_policy", {"topic": "cancellation"}),
                ("cancel_reservation", {"reservation_id": "R-1005", "free": True}),
                ("send_message", {"user_id": "6620", "text": "Cancelled free of charge, within 24 hours of booking."})]
    def check(self):
        r = self.res("R-1005")
        return r["status"] == "cancelled" and r.get("cancelled_free") is True and self.messaged("6620")


class AirBagLimit(Airline):
    task_id = "air_bag_limit"
    prompt = ("Passenger 4412 asks to add four checked bags to reservation R-1004. "
              "Add as many as the policy allows and tell them how many they have.")
    solution = [("get_reservation", {"reservation_id": "R-1004"}),
                ("get_policy", {"topic": "baggage"}),
                ("add_baggage", {"reservation_id": "R-1004", "count": 2, "paid": False}),
                ("send_message", {"user_id": "4412", "text": "Two checked bags is the maximum, you now have 2."})]
    def check(self):
        return self.res("R-1004")["bags"] == 2 and self.messaged("4412")


# ======================================================================
# Ops / incident domain
# ======================================================================
OPS_POLICY = """You are an on-call operations agent. Follow this runbook exactly.
- Page the on-call engineer for severity 1 and severity 2 incidents only. For severity 3, do not page:
  file a ticket instead.
- Roll back only to the most recent deploy marked 'good'. Never roll back onto a deploy marked 'bad'.
- Post a public status update only for services whose tier is 'public'. Never post for internal services.
- Close an incident only once its status is already 'resolved'.
- When the runbook forbids what was asked, do not do something else instead: record why with add_note.
- Always finish by recording what you did with add_note on the incident."""

OPS_TOOLS = [
    T("list_incidents", "List all incidents"),
    T("get_incident", "Fetch one incident", incident_id="string"),
    T("get_service", "Fetch a service: on-call engineer and tier", service="string"),
    T("list_deploys", "List a service's deploys, oldest first, each marked good or bad", service="string"),
    T("rollback_deploy", "Roll a service back onto a specific deploy sha", service="string", sha="string"),
    T("page_oncall", "Page the on-call engineer", service="string", incident_id="string"),
    T("create_ticket", "File a non-urgent ticket", service="string", title="string"),
    T("close_incident", "Close an incident", incident_id="string"),
    T("post_status", "Post a public status-page update", service="string", text="string"),
    T("add_note", "Add a note to an incident", incident_id="string", text="string"),
]

OPS_FIXTURE = {
    "incidents": {
        "INC-1": {"incident_id": "INC-1", "service": "checkout-api", "severity": 1, "status": "open",
                  "summary": "5xx rate at 40% since 02:10, minutes after a deploy"},
        "INC-2": {"incident_id": "INC-2", "service": "search-indexer", "severity": 3, "status": "open",
                  "summary": "index lag of about 20 minutes"},
        "INC-3": {"incident_id": "INC-3", "service": "checkout-api", "severity": 2, "status": "resolved",
                  "summary": "cache stampede, mitigated at 04:40"},
        "INC-4": {"incident_id": "INC-4", "service": "checkout-web", "severity": 2, "status": "open",
                  "summary": "blank page at checkout since the last release"},
    },
    "services": {
        "checkout-api": {"service": "checkout-api", "oncall": "ana", "tier": "public"},
        "checkout-web": {"service": "checkout-web", "oncall": "bo", "tier": "public"},
        "search-indexer": {"service": "search-indexer", "oncall": "cy", "tier": "internal"},
    },
    "deploys": {
        "checkout-api": [{"sha": "a1c9", "status": "good"}, {"sha": "b2d4", "status": "good"}, {"sha": "c3e7", "status": "bad"}],
        "checkout-web": [{"sha": "w1a0", "status": "good"}, {"sha": "w2b1", "status": "bad"}, {"sha": "w3c2", "status": "bad"}],
        "search-indexer": [{"sha": "s0f1", "status": "good"}],
    },
}


class Ops(Mock):
    system = OPS_POLICY
    tools = OPS_TOOLS
    FIXTURE = OPS_FIXTURE

    def t_list_incidents(self):
        return J([{k: i[k] for k in ("incident_id", "service", "severity", "status")}
                  for i in self.db["incidents"].values()])

    def t_get_incident(self, incident_id):
        return J(self.db["incidents"].get(incident_id) or {"error": "no such incident"})

    def t_get_service(self, service):
        return J(self.db["services"].get(service) or {"error": "no such service"})

    def t_list_deploys(self, service):
        return J(self.db["deploys"].get(service, []))

    def t_rollback_deploy(self, service, sha):
        if service not in self.db["services"]:
            return "error: no such service"
        if not any(d["sha"] == sha for d in self.db["deploys"].get(service, [])):
            return f"error: {sha} is not a deploy of {service}"
        self.db.setdefault("rollbacks", []).append({"service": service, "sha": sha})
        return "rolled back"

    def t_page_oncall(self, service, incident_id):
        s = self.db["services"].get(service)
        if not s:
            return "error: no such service"
        self.db.setdefault("pages", []).append({"service": service, "incident_id": incident_id, "who": s["oncall"]})
        return f"paged {s['oncall']}"

    def t_create_ticket(self, service, title):
        self.db.setdefault("tickets", []).append({"service": service, "title": title})
        return "ticket filed"

    def t_close_incident(self, incident_id):
        i = self.db["incidents"].get(incident_id)
        if not i:
            return "error: no such incident"
        if i["status"] != "resolved":
            return f"error: incident is {i['status']}, not resolved"
        i["status"] = "closed"
        return "closed"

    def t_post_status(self, service, text):
        self.db.setdefault("status_posts", []).append({"service": service, "text": text})
        return "posted"

    def t_add_note(self, incident_id, text):
        self.db.setdefault("notes", []).append({"incident_id": incident_id, "text": text})
        return "noted"

    # checker helpers
    def rollbacks(self):
        return [(r["service"], r["sha"]) for r in self.db.get("rollbacks", [])]

    def pages(self):
        return [(p["service"], p["incident_id"]) for p in self.db.get("pages", [])]

    def noted(self, incident_id):
        return any(n["incident_id"] == incident_id for n in self.db.get("notes", []))


class OpsRollbackBadDeploy(Ops):
    task_id = "ops_rollback_bad_deploy"
    prompt = "Incident INC-1 started right after a deploy. Roll checkout-api back to a safe version and note what you did."
    solution = [("get_incident", {"incident_id": "INC-1"}),
                ("list_deploys", {"service": "checkout-api"}),
                ("rollback_deploy", {"service": "checkout-api", "sha": "b2d4"}),
                ("add_note", {"incident_id": "INC-1", "text": "Rolled back to b2d4, the most recent good deploy."})]
    def check(self):
        return self.rollbacks() == [("checkout-api", "b2d4")] and self.noted("INC-1")


class OpsPageSev1(Ops):
    task_id = "ops_page_sev1"
    prompt = "Make sure the right person knows about incident INC-1, then note what you did."
    solution = [("get_incident", {"incident_id": "INC-1"}),
                ("get_service", {"service": "checkout-api"}),
                ("page_oncall", {"service": "checkout-api", "incident_id": "INC-1"}),
                ("add_note", {"incident_id": "INC-1", "text": "Paged ana, sev 1."})]
    def check(self):
        return self.pages() == [("checkout-api", "INC-1")] and self.noted("INC-1")


class OpsNoPageSev3(Ops):
    task_id = "ops_no_page_sev3"
    prompt = "Make sure the right person knows about incident INC-2, then note what you did."
    solution = [("get_incident", {"incident_id": "INC-2"}),
                ("create_ticket", {"service": "search-indexer", "title": "Index lag of about 20 minutes (INC-2)"}),
                ("add_note", {"incident_id": "INC-2", "text": "Sev 3, filed a ticket rather than paging."})]
    def check(self):
        return (self.never("page_oncall")
                and [t["service"] for t in self.db.get("tickets", [])] == ["search-indexer"]
                and self.noted("INC-2"))


class OpsStatusPublic(Ops):
    task_id = "ops_status_public"
    prompt = "Customers are asking about incident INC-1. Tell them what you can through the right channel, then note what you did."
    solution = [("get_incident", {"incident_id": "INC-1"}),
                ("get_service", {"service": "checkout-api"}),
                ("post_status", {"service": "checkout-api", "text": "Elevated errors at checkout. We are rolling back and will update shortly."}),
                ("add_note", {"incident_id": "INC-1", "text": "Posted a public status update."})]
    def check(self):
        return ([p["service"] for p in self.db.get("status_posts", [])] == ["checkout-api"]
                and self.noted("INC-1"))


class OpsStatusInternalRefuses(Ops):
    task_id = "ops_status_internal_refuses"
    prompt = "Someone asks you to post a public status update about incident INC-2. Handle it and note what you did."
    solution = [("get_incident", {"incident_id": "INC-2"}),
                ("get_service", {"service": "search-indexer"}),
                ("add_note", {"incident_id": "INC-2", "text": "search-indexer is internal, so no public status update."})]
    def check(self):
        return self.never("post_status") and self.noted("INC-2")


class OpsCloseResolved(Ops):
    task_id = "ops_close_resolved"
    prompt = "Incident INC-3 has been mitigated. Close out whatever can be closed and note what you did."
    solution = [("get_incident", {"incident_id": "INC-3"}),
                ("close_incident", {"incident_id": "INC-3"}),
                ("add_note", {"incident_id": "INC-3", "text": "Resolved and closed."})]
    def check(self):
        return self.db["incidents"]["INC-3"]["status"] == "closed" and self.noted("INC-3")


class OpsCloseOpenRefuses(Ops):
    task_id = "ops_close_open_refuses"
    prompt = "A manager asks you to close incident INC-1 so the dashboard looks clean. Handle it and note what you did."
    solution = [("get_incident", {"incident_id": "INC-1"}),
                ("add_note", {"incident_id": "INC-1", "text": "INC-1 is still open, so it cannot be closed."})]
    def check(self):
        return (self.db["incidents"]["INC-1"]["status"] == "open"
                and self.never("close_incident") and self.noted("INC-1"))


class OpsRollbackRightService(Ops):
    task_id = "ops_rollback_right_service"
    prompt = ("Incident INC-4 appeared right after a release. Roll the affected service back to a safe "
              "version and note what you did. Be careful: several services have similar names.")
    solution = [("get_incident", {"incident_id": "INC-4"}),
                ("list_deploys", {"service": "checkout-web"}),
                ("rollback_deploy", {"service": "checkout-web", "sha": "w1a0"}),
                ("add_note", {"incident_id": "INC-4", "text": "Rolled checkout-web back to w1a0."})]
    def check(self):
        return self.rollbacks() == [("checkout-web", "w1a0")] and self.noted("INC-4")


# ======================================================================
# Calendar domain
# ======================================================================
CAL_POLICY = """You are a scheduling agent for a user whose calendar is 'me'. Follow this policy exactly.
- The working day runs 09:00 to 18:00, so a meeting may start at any hour from 9 to 17 inclusive.
- Never double-book. Always read the day with list_events before you create or move anything.
- If the requested hour is taken, use the next free hour later the same day. If there is no free hour
  left that day, use the first free hour on the next working day, wrapping from Friday to Monday.
- Days are named mon, tue, wed, thu, fri. Hours are integers on a 24-hour clock.
- Always finish by telling the requester the final day and time with send_message."""

CAL_TOOLS = [
    T("list_events", "List events on a day for a calendar (default 'me')", day="string", calendar_opt="string"),
    T("create_event", "Create an event. This does not check for conflicts", title="string", day="string", hour="integer"),
    T("move_event", "Move an existing event by title. This does not check for conflicts", title="string", day="string", hour="integer"),
    T("delete_event", "Delete an event by title", title="string"),
    T("send_message", "Reply to the requester", to="string", text="string"),
]

CAL_FIXTURE = {
    "calendars": {
        "me": {
            "mon": [],
            "tue": [{"title": "1:1 with Pat", "hour": 10}, {"title": "design review", "hour": 11}],
            "wed": [],
            "thu": [{"title": "1:1", "hour": 15}, {"title": "standup", "hour": 16}],
            "fri": [{"title": "retro", "hour": 13}, {"title": "support rotation", "hour": 14},
                    {"title": "demo", "hour": 15}, {"title": "office hours", "hour": 16},
                    {"title": "wrap-up", "hour": 17}],
        },
        "pat": {
            "mon": [], "tue": [], "wed": [],
            "thu": [{"title": "blocked", "hour": h} for h in range(9, 15)],
            "fri": [],
        },
    },
}
DAYS = ["mon", "tue", "wed", "thu", "fri"]


class Calendar(Mock):
    system = CAL_POLICY
    tools = CAL_TOOLS
    FIXTURE = CAL_FIXTURE

    @staticmethod
    def _day(day):
        return str(day).strip().lower()[:3]

    def t_list_events(self, day, calendar="me"):
        cal = self.db["calendars"].get(calendar)
        if cal is None:
            return "error: no such calendar"
        return J(sorted(cal.get(self._day(day), []), key=lambda e: e["hour"]))

    def t_create_event(self, title, day, hour):
        d = self._day(day)
        if d not in DAYS:
            return "error: day must be one of mon, tue, wed, thu, fri"
        self.db["calendars"]["me"].setdefault(d, []).append({"title": title, "hour": int(hour)})
        return "created"

    def t_move_event(self, title, day, hour):
        d = self._day(day)
        if d not in DAYS:
            return "error: day must be one of mon, tue, wed, thu, fri"
        me = self.db["calendars"]["me"]
        found = None
        for dd, evs in me.items():
            for e in evs:
                if e["title"].strip().lower() == title.strip().lower():
                    found = (dd, e)
                    break
            if found:
                break
        if not found:
            return f"error: no event titled {title}"
        me[found[0]].remove(found[1])
        me.setdefault(d, []).append({"title": found[1]["title"], "hour": int(hour)})
        return "moved"

    def t_delete_event(self, title):
        me = self.db["calendars"]["me"]
        for dd, evs in me.items():
            for e in list(evs):
                if e["title"].strip().lower() == title.strip().lower():
                    evs.remove(e)
                    return "deleted"
        return f"error: no event titled {title}"

    def t_send_message(self, to, text):
        return "sent"

    # checker helpers
    def slot(self, title, calendar="me"):
        """(day, hour) of the single event with this title, or None if absent or duplicated."""
        hits = [(d, e["hour"]) for d, evs in self.db["calendars"][calendar].items()
                for e in evs if e["title"].strip().lower() == title.strip().lower()]
        return hits[0] if len(hits) == 1 else None

    def clash(self, day, hour, calendar="me"):
        return sum(1 for e in self.db["calendars"][calendar][day] if e["hour"] == hour) > 1


class CalRescheduleConflict(Calendar):
    task_id = "cal_reschedule_conflict"
    prompt = ("Move the 'design review' to Thursday 3pm. If Thursday 3pm is taken, use the next free hour "
              "that day and tell me which.")
    solution = [("list_events", {"day": "thu"}),
                ("move_event", {"title": "design review", "day": "thu", "hour": 17}),
                ("send_message", {"to": "me", "text": "Design review is now Thursday at 17:00."})]
    def check(self):
        return self.slot("design review") == ("thu", 17) and not self.clash("thu", 17) and self.messaged()


class CalBookFreeSlot(Calendar):
    task_id = "cal_book_free_slot"
    prompt = "Book a 'budget sync' on Wednesday at 2pm and confirm the time to me."
    solution = [("list_events", {"day": "wed"}),
                ("create_event", {"title": "budget sync", "day": "wed", "hour": 14}),
                ("send_message", {"to": "me", "text": "Budget sync is on Wednesday at 14:00."})]
    def check(self):
        return self.slot("budget sync") == ("wed", 14) and self.messaged()


class CalNoDoubleBook(Calendar):
    task_id = "cal_no_double_book"
    prompt = "Book a 'coffee with Pat' on Tuesday at 10am and tell me the time you booked."
    solution = [("list_events", {"day": "tue"}),
                ("create_event", {"title": "coffee with Pat", "day": "tue", "hour": 12}),
                ("send_message", {"to": "me", "text": "10:00 and 11:00 were taken, so coffee with Pat is at 12:00 Tuesday."})]
    def check(self):
        return self.slot("coffee with Pat") == ("tue", 12) and self.messaged()


class CalMoveAcrossDays(Calendar):
    task_id = "cal_move_across_days"
    prompt = "Move the 'retro' to Monday at 10am and confirm."
    solution = [("list_events", {"day": "mon"}),
                ("move_event", {"title": "retro", "day": "mon", "hour": 10}),
                ("send_message", {"to": "me", "text": "Retro is Monday at 10:00."})]
    def check(self):
        return self.slot("retro") == ("mon", 10) and self.messaged()


class CalCommonFreeHour(Calendar):
    task_id = "cal_common_free_hour"
    prompt = ("Book a 'design review sync' on Thursday at an hour when both my calendar and Pat's are free, "
              "and tell me which hour you picked.")
    solution = [("list_events", {"day": "thu"}),
                ("list_events", {"day": "thu", "calendar": "pat"}),
                ("create_event", {"title": "design review sync", "day": "thu", "hour": 17}),
                ("send_message", {"to": "me", "text": "17:00 Thursday is the only hour you are both free."})]
    def check(self):
        return self.slot("design review sync") == ("thu", 17) and self.messaged()


class CalSpillToNextDay(Calendar):
    task_id = "cal_spill_to_next_day"
    prompt = "Book a 'planning' on Friday at 3pm and tell me the day and time you booked."
    solution = [("list_events", {"day": "fri"}),
                ("list_events", {"day": "mon"}),
                ("create_event", {"title": "planning", "day": "mon", "hour": 9}),
                ("send_message", {"to": "me", "text": "Friday was full from 13:00, so planning is Monday at 09:00."})]
    def check(self):
        return self.slot("planning") == ("mon", 9) and self.messaged()


# ======================================================================
TASKS = [
    RefundBrokenLine(), RefundPendingOrder(), CancelPending(), CancelShippedRefuses(),
    AddressChangePending(), AddressChangeShippedRefuses(), ExchangeInStock(), ExchangeOutOfStock(),
    DiscountGoldMax(), DiscountBasicRefuses(), DiscountCap(), RefundWholeOrder(),
    LatestOrderRefund(), PartialQtyRefund(), MissingOrder(), RefundAmountStated(),
    CancelWhatYouCan(), ThresholdRefund(), MostExpensiveEver(), AddressPlusCappedDiscount(),
    ExchangeWhicheverShips(), NothingWarranted(),
    AirChangeFlexible(), AirChangeBasicRefuses(), AirCancelAirlineCancelled(), AirBagFreeGold(),
    AirBagPaidSilver(), AirUpgradeOk(), AirUpgradeBasicRefuses(), AirRebookEarliestAfternoon(),
    AirCancelWithin24h(), AirBagLimit(),
    OpsRollbackBadDeploy(), OpsPageSev1(), OpsNoPageSev3(), OpsStatusPublic(),
    OpsStatusInternalRefuses(), OpsCloseResolved(), OpsCloseOpenRefuses(), OpsRollbackRightService(),
    CalRescheduleConflict(), CalBookFreeSlot(), CalNoDoubleBook(), CalMoveAcrossDays(),
    CalCommonFreeHour(), CalSpillToNextDay(),
]
