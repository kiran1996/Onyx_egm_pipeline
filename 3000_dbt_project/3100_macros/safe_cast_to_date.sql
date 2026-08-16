{% macro create_safe_cast_to_date() %}
create or replace function safe_cast_to_date(value text)
returns date
language plpgsql
immutable
as $BODY$
begin
    return value::date;
exception when others then
    return null;
end;
$BODY$
{% endmacro %}
