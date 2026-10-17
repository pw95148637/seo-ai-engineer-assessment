"""Outcome rules and Hermes learning surfaces, separate from Hermes imports so they are testable offline."""
TOOLS={'research_status','research_fetch','research_search','research_offpage','research_evidence','research_finish'}
SKILL_READ_TOOLS={'skills_list','skill_view'}
HERMES_WRITE_TOOLS={'memory','skill_manage'}
# Custom toolset for frozen runs: skills can be listed and read, never written.
READ_ONLY_SKILLS_TOOLSET='soulo_skills_read'
# Hermes surface per learning setting. off: no Hermes memory or skills (v0.7 runs). learn: the research tools plus
# Hermes memory and skills, with the end-of-turn review. frozen: learned memory is loaded into the system prompt and
# skills can be read, but nothing can be written. feedback: one review turn with memory and skills, no research tools.
HERMES_MODES={
 'off':dict(toolsets=['soulo_research'],skip_memory=True,review=False,tools=TOOLS),
 'learn':dict(toolsets=['soulo_research','memory','skills'],skip_memory=False,review=True,
              tools=TOOLS|SKILL_READ_TOOLS|HERMES_WRITE_TOOLS),
 'frozen':dict(toolsets=['soulo_research',READ_ONLY_SKILLS_TOOLSET],skip_memory=False,review=False,
               tools=TOOLS|SKILL_READ_TOOLS),
 'feedback':dict(toolsets=['memory','skills'],skip_memory=False,review=True,tools=SKILL_READ_TOOLS|HERMES_WRITE_TOOLS)}
def readiness(auth,tools,expected=TOOLS):
    # Never copy auth objects or credentials into output. Only these booleans are public.
    out={'provider':'openai-codex','logged_in':bool(auth.get('logged_in')),
         'rate_limited':bool(auth.get('rate_limited')),'expected_tools':sorted(expected),
         'actual_tools':sorted(tools),'model_called':False}
    out['ready']=out['logged_in'] and not out['rate_limited'] and set(tools)==set(expected)
    out['blocker']='' if out['ready'] else ('unexpected_tools' if set(tools)!=set(expected) else ('quota' if out['rate_limited'] else 'oauth_required'))
    return out

def outcome(result,trace,smoke=False):
    calls=[x for x in trace if x['kind']=='tool_call']
    submitted=any(x['kind']=='report' for x in trace)
    complete=result.get('completed') is True and not result.get('failed') and not result.get('partial')
    if not complete:return 'model_failed_or_partial',3
    if not calls:return 'no_autonomous_tool_use',3
    if not smoke and not submitted:return 'missing_controller_report',3
    return ('smoke_complete' if smoke else 'research_complete'),0

def feedback_outcome(result,trace):
    """A feedback turn completes without research tools; any research call means the session left its scope."""
    complete=result.get('completed') is True and not result.get('failed') and not result.get('partial')
    if not complete:return 'model_failed_or_partial',3
    if any(x['kind']=='tool_call' for x in trace):return 'feedback_used_research_tools',3
    return 'feedback_complete',0

def review_record(seen_thread,records,actions,alive):
    """Summarize the end-of-turn review from its log records (logger agent.background_review).

    completed needs the completion line with a result other than error; a review still running when the wait ended
    is timed_out, and its partial writes stay on disk."""
    done=[r for r in records if r.get('message','').startswith('Background review complete')]
    failed=[r for r in records if 'review failed' in r.get('message','') or 'review skipped' in r.get('message','')]
    usage=None;result=None
    if done:
        a=done[-1].get('args') or []
        if len(a)>=5:usage=dict(api_calls=a[0],input=a[1],output=a[2],cache_read=a[3]);result=a[4]
    triggered=bool(seen_thread or records)
    completed=bool(done) and result!='error' and not alive
    return dict(triggered=triggered,completed=completed,timed_out=bool(alive),result=result,usage=usage,
                actions=list(actions),warnings=[r['message'] for r in failed])
