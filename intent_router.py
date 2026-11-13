"""Central precedence for supported assistant queries.

Recognition only: execution, data access and model calls remain in their
respective services. The first matched route owns the request, including
validation errors, so a later route cannot reinterpret an ambiguous question.
"""
import analysis_planner
import conversation_query
import network_query
import query_context
import query_router
import ranking_planner
from smart_query import highest_resolution_plan


def route(messages):
    """Return (route name, plan), or (general, None) for the model fallback."""
    last = messages[-1]['content']
    candidates = (
        ('suspension_growth', lambda: conversation_query.growth_plan(messages)),
        ('daily_comparison', lambda: conversation_query.daily_comparison_plan(messages)),
        ('suspension', lambda: conversation_query.suspension_plan(messages)),
        ('ranked_comparison', lambda: query_router.ranked_comparison_plan(messages)),
        ('city_comparison', lambda: query_router.city_comparison_plan(messages)),
        ('suspension_reason', lambda: query_router.suspension_reason_plan(messages)),
        ('analysis', lambda: analysis_planner.should_plan(messages)),
        ('ranking', lambda: ranking_planner.should_plan(messages)),
        ('highest_resolution', lambda: highest_resolution_plan(last)),
        ('network_comparison', lambda: network_query.comparison_plan(last)),
        ('network_overview', lambda: network_query.overview_plan(messages)),
        ('network_metric', lambda: network_query.local_plan(last) or query_context.resolve_network_followup(messages)),
    )
    for name, recognize in candidates:
        plan = recognize()
        if plan:
            return name, plan
    return 'general', None
