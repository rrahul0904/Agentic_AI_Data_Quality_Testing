from shiftforge.rules import apply_rules


def test_bigquery_rules():
    sql = "SELECT IFNULL(name,'x'), COUNTIF(active) FROM `p.d.t`"
    out, hits = apply_rules(sql)
    assert "COALESCE(" in out
    assert "SUM(CASE WHEN active THEN 1 ELSE 0 END)" in out
    assert "p.d.t" in out and "`" not in out
    assert {h.rule_id for h in hits} >= {"BQ001", "BQ003", "BQ004"}


def test_date_add():
    out, _ = apply_rules("SELECT DATE_ADD(order_date, INTERVAL 7 DAY)")
    assert "DATEADD(day, 7, order_date)" in out
