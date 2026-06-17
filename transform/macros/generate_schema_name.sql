-- Override dbt's default schema naming behaviour.
-- By default dbt concatenates: profile_schema + "_" + model_schema
-- This macro makes it use ONLY the model's schema config when one is provided
 
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}