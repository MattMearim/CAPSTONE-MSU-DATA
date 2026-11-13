"""Review AI findings beside charts; repairs always create validated copies."""
import streamlit as st


def render_agent_panel(event,state,api_post,friendly_error,prefix,navigate_event):
    latest=state.get('latest'); report=state.get('report')
    pending=latest and latest['status'] in {'queued','running'}
    count=len((report or {}).get('findings',[]))
    with st.expander(f'AI quality review · {count} '+('flag' if count==1 else 'flags'),expanded=bool(pending)):
        st.caption('AI suggestions · human review required')
        if not state.get('enabled'): st.info('Quality agent off. Enable it in AI settings.')
        if st.button('Run AI quality review',key=prefix+'_qa_run',disabled=not state.get('enabled') or bool(pending)):
            try: api_post(f"/events/{event['event_id']}/quality-agent",{}); st.rerun()
            except Exception as exc: st.error(friendly_error(exc))
        if st.button('Refresh AI flags',key=prefix+'_qa_refresh'): st.rerun()
        if latest:
            if pending: st.info(latest.get('message','Review queued'))
            elif latest['status'] in {'failed','cancelled','stale'}:
                st.warning('The latest quality review is '+latest['status']+'.')
                st.text(latest.get('message',latest['status']))
        if not report:
            st.caption('No completed AI review yet. Existing deterministic validation still runs.')
            if latest and latest.get('status') in {'failed','cancelled','stale'}:
                with st.expander('Latest review diagnostics'): st.json(latest)
            return None
        if latest and latest['run_id']!=report['run_id']: st.caption('Showing the previous completed report while the latest review is pending or unavailable.')
        findings=report.get('findings',[])
        with st.expander("Model's draft summary"):
            st.text(report.get('summary',''))
        generation=report.get('generation',{})
        st.caption(f"Model: {generation.get('model','unknown')} · report {report['run_id']}")
        coverage=report.get('coverage',{})
        st.caption(f"{coverage.get('directly_inspected_samples',0):,} / {coverage.get('total_samples',0):,} samples inspected · partial coverage may miss issues")
        if not findings:
            st.info('No suspicious findings were proposed in this bounded review. This is not proof that the dataset is error-free.')
            return report
        by_id={item['finding_id']:item for item in findings}
        choice=st.selectbox('Inspect an AI finding',list(by_id),format_func=lambda key:by_id[key]['title']+' · '+by_id[key]['severity'],key=prefix+'_qa_finding_'+report['run_id'])
        finding=by_id[choice]
        st.text(finding['title'])
        st.text(finding['explanation']); st.text('Suggested check: '+finding['recommended_check'])
        st.caption(f"Category: {finding['category']} · model confidence {finding['confidence']:.0%} (not calibrated) · review: {finding.get('review',{}).get('decision','unreviewed')}")
        if finding.get('anchors'): st.dataframe(finding['anchors'],hide_index=True,width='stretch')
        reviewer=st.text_input('Quality reviewer name',key=prefix+'_qa_reviewer')
        comments=st.text_input('Review comments',key=prefix+'_qa_comments_'+choice)
        left,right=st.columns(2)
        for column,decision,label in [(left,'accept','Accept this flag'),(right,'dismiss','Dismiss this flag')]:
            if column.button(label,key=prefix+'_qa_'+decision+'_'+choice,disabled=not reviewer.strip(),width='stretch'):
                try:
                    api_post(f"/quality-agent/runs/{report['run_id']}/findings/{choice}/review",{'decision':decision,'reviewer':reviewer.strip(),'comments':comments})
                    st.rerun()
                except Exception as exc: st.error(friendly_error(exc))
        repair=finding.get('repair',{'action':'review_only'})
        if repair['action']!='review_only':
            st.write('Proposed repair:'); st.json(repair)
            if finding.get('repair_event_id'):
                st.success('A corrected copy already exists: '+finding['repair_event_id'])
                if st.button('Open corrected copy',key=prefix+'_qa_open_'+choice,on_click=navigate_event,args=(finding['repair_event_id'],)): pass
            else:
                confirmed=st.checkbox('I authorize this exact proposal as a separate corrected copy; keep the original intact.',key=prefix+'_qa_authorize_'+choice)
                if st.button('Create corrected copy',key=prefix+'_qa_repair_'+choice,
                             disabled=not confirmed or not reviewer.strip() or finding.get('review',{}).get('decision')!='accept'):
                    try:
                        result=api_post(f"/quality-agent/runs/{report['run_id']}/findings/{choice}/repair",{'reviewer':reviewer.strip(),'confirmed':True,'proposal_hash':finding['proposal_hash']})
                        st.success('Created '+result['event_id']+'. Original evidence is preserved.'); st.rerun()
                    except Exception as exc: st.error(friendly_error(exc))
        with st.expander('Read-only investigation and audit details'):
            st.json({'source_hash':report['source_hash'],'coverage':coverage,'trace':report.get('trace',[]),'validation_notes':report.get('validation_notes',[])})
        return report


def render_quality_chart(event,api_get,api_post,friendly_error,navigate_event,render_chart,*,prefix):
    try: initial=api_get(f"/events/{event['event_id']}/quality-agent")
    except Exception:
        render_chart(None); return
    pending=initial.get('latest',{}).get('status') in {'queued','running'} if initial.get('latest') else False

    @st.fragment(run_every='3s' if pending else None)
    def chart():
        try:
            state=api_get(f"/events/{event['event_id']}/quality-agent")
            if pending and (state.get('latest') or {}).get('status') not in {'queued','running'}: st.rerun()
            render_chart(state.get('report'))
            render_agent_panel(event,state,api_post,friendly_error,prefix,navigate_event)
        except Exception as exc:
            st.error('AI quality review: '+friendly_error(exc)); render_chart(None)
    chart()
