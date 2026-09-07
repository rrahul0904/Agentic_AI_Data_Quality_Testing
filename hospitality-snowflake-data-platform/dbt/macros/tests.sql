{% test value_between(model, column_name, min_value, max_value) %}
select * from {{ model }} where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}

{% test date_order(model, start_column, end_column) %}
select * from {{ model }} where {{ end_column }} < {{ start_column }}
{% endtest %}

