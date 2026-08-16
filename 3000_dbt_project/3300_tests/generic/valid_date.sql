{% test valid_date(model, column_name) %}
-- Fails if the column can't be cast to a real calendar date.
-- Relies on safe_cast_to_date (3100_macros/safe_cast_to_date.sql), which wraps a
-- ::date cast in exception handling so a malformed value is a graceful test
-- failure here rather than a hard cast error later (e.g. in a staging model).

select *
from {{ model }}
where safe_cast_to_date({{ column_name }}) is null

{% endtest %}
