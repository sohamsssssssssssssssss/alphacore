from datetime import date, datetime, time, timezone
import json
import subprocess

import numpy as np
import pandas as pd
import pytest

import momentum_forward as f
from momentum_12_1 import make_selectors
from basket_backtest import simulate_rebalanced
from prices import point_in_time_adv
from engines.cost_model import CostModel


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(f, 'ROOT', tmp_path)
    monkeypatch.setattr(f, 'FORWARD', tmp_path/'research/momentum/forward')
    monkeypatch.setattr(f, 'SNAPSHOTS', tmp_path/'data_snapshots/momentum-forward')
    monkeypatch.setattr(f, 'UNIVERSE', tmp_path/'universe.txt')
    f.FORWARD.mkdir(parents=True)
    f.UNIVERSE.write_text('\n'.join(f'N{i:02d}' for i in range(51)))
    (f.FORWARD/'nse_holidays.txt').write_text('# synthetic only\n2026-01-01\n2027-01-02\n2028-01-01\n')
    monkeypatch.setattr(f, 'git', lambda *args: 'a'*40 if args == ('rev-parse', 'HEAD') else pytest.fail(f'unmocked git: {args}'))
    monkeypatch.setattr(f, 'gh', lambda *args: pytest.fail('unmocked GitHub request'))
    monkeypatch.setattr(f.yf, 'download', lambda *args, **kw: pytest.fail('network in synthetic test'))


def panel():
    index = pd.bdate_range('2025-09-01', '2027-02-02')
    prices = 100*np.exp(np.arange(len(index))[:, None] * np.linspace(.0001, .001, 51))
    c = pd.DataFrame(prices, index=index, columns=[f'N{i:02d}' for i in range(51)])
    return pd.concat({'Open': c*1.002, 'High': c*1.01, 'Low': c*.99,
                      'Close': c, 'Volume': c*0+200000.}, axis=1)


def at(d, hour=16):
    return datetime.combine(d, time(hour), f.IST)


def log(bars, day):
    return f.log_month(day, bars.loc[:str(day)], {}, now=at(day))


def receipt(month, stamp):
    (f.FORWARD/f'{month}.receipt.json').write_bytes(f.encoded({'commit_sha': 'a'*40, 'published_at_utc': stamp.isoformat()}))


@pytest.mark.parametrize('day', [date(2026,11,16), date(2026,11,27)])
def test_mid_month_refused(day):
    with pytest.raises(ValueError, match='month-end'):
        log(panel(), day)
    assert not list(f.FORWARD.glob('2026-*.json'))


def test_later_session_refused():
    with pytest.raises(ValueError, match='newest session'):
        f.log_month(date(2026,11,30), panel().loc[:'2026-12-01'], {}, now=at(date(2026,11,30)))


def test_close_time_and_missing_year_refused():
    bars=panel()
    with pytest.raises(ValueError, match='15:30'):
        f.log_month(date(2026,11,30), bars.loc[:'2026-11-30'], {}, now=at(date(2026,11,30),15))
    (f.FORWARD/'nse_holidays.txt').write_text('2025-01-01\n')
    with pytest.raises(ValueError, match='no NSE holiday'):
        log(bars,date(2026,11,30))


def test_december_log_needs_next_years_holidays():
    bars=panel()
    (f.FORWARD/'nse_holidays.txt').write_text('2026-01-26\n')
    with pytest.raises(ValueError, match='no NSE holiday entries for 2027'):
        log(bars,date(2026,12,31))
    (f.FORWARD/'nse_holidays.txt').write_text('2026-01-26\n2027-01-01\n')
    assert f.read(log(bars,date(2026,12,31)))['execution_session']=='2027-01-04'


def test_last_weekday_holiday_allows_earlier_month_end():
    (f.FORWARD/'nse_holidays.txt').write_text('2026-11-30\n')
    p=log(panel(),date(2026,11,27))
    assert f.read(p)['execution_session']=='2026-12-01'


def test_selection_matches_runner_and_exclusive_create():
    bars=panel(); d=date(2026,11,30)
    path=log(bars,d); original=path.read_bytes()
    snap=f.load_snapshot('2026-11',f.read(path))
    b,m,info=make_selectors(snap['Close'],snap['Volume'])
    names=info(d)['eligible_set']; rec=f.read(path)
    assert rec['basket']==b(snap['Close'],d,names)
    assert rec['benchmark']==m(snap['Close'],d,names)
    assert len(rec['signals'])==51
    with pytest.raises(FileExistsError):
        log(bars,d)
    assert path.read_bytes()==original
    assert len((f.FORWARD/'MANIFEST.jsonl').read_text().splitlines())==1


@pytest.mark.parametrize('carried', [False,True])
def test_three_month_mark_matches_simulator_to_1e12(monkeypatch,carried):
    bars=panel(); dates=[date(2026,11,30),date(2026,12,31),date(2027,1,29)]
    if carried:
        bars.loc['2027-01-01',('Open','N49')]=np.nan
        bars.loc['2027-01-01',('Close','N49')]=np.nan
    monkeypatch.setattr(f,'remote_log',lambda *_: datetime(2026,11,30,tzinfo=timezone.utc))
    for d in dates:
        rec=f.read(log(bars,d)); month=rec['month']; ex=date.fromisoformat(rec['execution_session'])
        receipt(month,at(d))
        state=f.mark_month(month,bars.loc[:str(ex)],now=at(ex))
    b,m,_=make_selectors(bars['Close'],bars['Volume'])
    history=point_in_time_adv(bars['Close'],bars['Volume'],[d.date() for d in bars.index])
    for side,sel in [('basket',b),('benchmark',m)]:
        sim=simulate_rebalanced(bars['Close'],bars['Open'],{d:history[d] for d in dates},dates,
                                cost_model=CostModel(brokerage_per_trade=0),budget=f.BUDGET,spread_bps=30,
                                select=sel,prior_close_carry=True,held_adv_history=history)
        got=[r['period_returns'][side] for r in state['months'][:-1]]
        assert got==pytest.approx(sim['period_returns'],abs=1e-12,rel=0)
        assert state['accounts'][side]['equity']==pytest.approx(sim['final_equity'],rel=1e-12)
        if carried:
            assert state['months'][1][side]['carried_names']==['N49']
            assert state['months'][2][side]['amendment_3_counts']['held_adv_fallback']==1
    original=(f.FORWARD/'state.json').read_bytes()
    f.mark_month('2027-01',pd.DataFrame())
    assert (f.FORWARD/'state.json').read_bytes()==original
    f.report()
    assert 'IR' not in (f.FORWARD/'REPORT.md').read_text()


@pytest.mark.parametrize('stamp,late', [('2026-12-01T03:44:59+00:00',False),('2026-12-01T03:45:00+00:00',True),('2026-12-01T03:45:01+00:00',True)])
def test_receipt_timestamp_decides_lateness_not_commit_time(monkeypatch,stamp,late):
    rec=f.read(log(panel(),date(2026,11,30)))
    receipt('2026-11',datetime.fromisoformat(stamp))
    monkeypatch.setattr(f,'remote_log',lambda *_: datetime(2026,12,5,tzinfo=timezone.utc))
    assert f.is_late('2026-11',rec) is late


def test_missing_receipt_and_remote_mismatch_are_late(monkeypatch):
    rec=f.read(log(panel(),date(2026,11,30)))
    monkeypatch.setattr(f,'git',lambda *_: '2000-01-01T00:00:00Z')
    assert f.is_late('2026-11',rec)
    receipt('2026-11',at(date(2026,11,30)))
    monkeypatch.setattr(f,'remote_log',lambda *_: (_ for _ in ()).throw(ValueError('hash mismatch')))
    assert f.is_late('2026-11',rec)


def test_late_log_excludes_following_period_not_preceding(monkeypatch):
    bars=panel()
    monkeypatch.setattr(f,'remote_log',lambda *_: datetime(2026,11,30,tzinfo=timezone.utc))
    for d in [date(2026,11,30),date(2026,12,31),date(2027,1,29)]:
        rec=f.read(log(bars,d)); ex=date.fromisoformat(rec['execution_session'])
        if rec['month']!='2026-12': receipt(rec['month'],at(d))
        state=f.mark_month(rec['month'],bars.loc[:str(ex)],now=at(ex))
    assert state['months'][0]['period_returns'] is not None
    assert state['months'][1]['late'] is True
    assert state['months'][1]['period_returns'] is None
    assert state['months'][2]['basket']['costs']>0


def test_mark_rejects_revised_snapshot_and_wrong_execution(monkeypatch):
    bars=panel(); rec=f.read(log(bars,date(2026,11,30)))
    with pytest.raises(ValueError,match='fresh next session'):
        f.mark_month('2026-11',bars.loc[:'2026-11-30'],now=at(date(2026,12,1)))
    p=f.SNAPSHOTS/'2026-11.csv'; p.write_bytes(p.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='hash mismatch'):
        f.mark_month('2026-11',bars.loc[:'2026-12-01'],now=at(date(2026,12,1)))
    assert not (f.FORWARD/'state.json').exists()


def mock_publication(monkeypatch,fail_push=False,fail_confirmation=False):
    calls=[]; tracked=set(); committed={}
    def git(*args):
        calls.append(args)
        if args[0]=='branch': return 'main'
        if args[0]=='diff': return ''
        if args[0]=='ls-files': return args[-1] if args[-1] in tracked else ''
        if args[0]=='add': tracked.update(args[2:]); return ''
        if args[0]=='commit':
            for p in args[args.index('--')+1:]: committed[p]=(f.ROOT/p).read_text()
            return ''
        if args[0]=='show': return committed[args[1].removeprefix('HEAD:')]
        if args[0]=='log': return 'a'*40
        if args[0]=='push':
            if fail_push: raise subprocess.CalledProcessError(1,args)
            return ''
        pytest.fail(str(args))
    monkeypatch.setattr(f,'git',git)
    def remote(*_):
        if fail_confirmation: raise ValueError('confirmation failed')
        return datetime(2026,11,30,12,tzinfo=timezone.utc)
    monkeypatch.setattr(f,'remote_log',remote)
    return calls


def test_publish_retries_only_publication_and_never_rewrites_log(monkeypatch):
    path=log(panel(),date(2026,11,30)); original=path.read_bytes()
    mock_publication(monkeypatch,fail_push=True)
    with pytest.raises(RuntimeError,match='--publish'):
        f.publish('2026-11')
    assert not (f.FORWARD/'2026-11.receipt.json').exists()
    calls=mock_publication(monkeypatch)
    assert f.main(['log','--publish','2026-11'])==0
    assert path.read_bytes()==original
    assert f.read(f.FORWARD/'2026-11.receipt.json')['published_at_utc']=='2026-11-30T12:00:00+00:00'
    assert len([x for x in calls if x[0]=='push'])==2
    for call in [x for x in calls if x[0]=='commit']:
        assert '--only' in call


def test_confirmation_failure_leaves_no_receipt(monkeypatch):
    log(panel(),date(2026,11,30))
    mock_publication(monkeypatch,fail_confirmation=True)
    with pytest.raises(RuntimeError,match='confirmation failed'): f.publish('2026-11')
    assert not (f.FORWARD/'2026-11.receipt.json').exists()


@pytest.mark.parametrize('valid', [17,18,24])
def test_final_report_only_at_fixed_end_and_minimum_18(valid):
    rows=[]; month='2026-11'
    for i in range(25):
        stats={'costs':1.,'turnover':.1,'invested_fraction':.995}
        rows.append({'month':month,'late':i<24-valid,'period_returns':None if i<24-valid or i==24 else {'basket':.02,'benchmark':.01,'active':.01+i*.0001},
                     'basket':stats,'benchmark':stats,'eligible_count':50})
        month=f.next_month(month)
    (f.FORWARD/'state.json').write_bytes(f.encoded({'months':rows}))
    f.report(); text=(f.FORWARD/'REPORT.md').read_text()
    assert ('IR:' in text)==(valid>=18)
    assert f'missed: {24-valid}' in text
    if valid>=18: assert 'consistent with the backtest' in text


def test_remote_confirmation_checks_server_date_ancestry_and_payload(monkeypatch):
    import base64
    path=log(panel(),date(2026,11,30)); commit='a'*40
    monkeypatch.setattr(f,'repo_name',lambda:'owner/repo')
    calls=[]
    def gh(*args):
        calls.append(args)
        endpoint=args[-1]
        if '/commits/' in endpoint:
            return 'HTTP/2 200 OK\nDate: Mon, 30 Nov 2026 12:00:00 GMT\n\n'+json.dumps({'sha':commit})
        if '/compare/' in endpoint: return json.dumps({'status':'ahead'})
        return json.dumps({'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode()})
    monkeypatch.setattr(f,'gh',gh)
    assert f.remote_log(commit,path)==datetime(2026,11,30,12,tzinfo=timezone.utc)
    assert len(calls)==3


def test_fetch_shape_and_420_day_start_without_network(monkeypatch):
    calls=[]
    raw=panel().xs('N00',axis=1,level=1).iloc[-2:]
    def download(symbol,**kwargs): calls.append((symbol,kwargs)); return raw.copy()
    monkeypatch.setattr(f.yf,'download',download)
    monkeypatch.setattr(f,'utcnow',lambda:datetime(2027,2,3,tzinfo=timezone.utc))
    bars,missing=f.fetch_bars(date(2027,1,29),['N00','N01','N02'])
    assert missing=={} and bars['Close'].shape==(2,3)
    assert all(kw['start']=='2025-12-05' and kw['auto_adjust'] is True for _,kw in calls)
    assert [s for s,_ in calls]==['N00.NS','N01.NS','N02.NS']


def test_failed_receipt_push_recovers_committed_receipt_without_rewriting_month(monkeypatch):
    path=log(panel(),date(2026,11,30)); original=path.read_bytes()
    mock_publication(monkeypatch)
    original_git=f.git
    pushes=[]
    def git(*args):
        if args[0]=='push':
            pushes.append(args)
            if len(pushes)==2: raise subprocess.CalledProcessError(1,args)
        return original_git(*args)
    monkeypatch.setattr(f,'git',git)
    with pytest.raises(RuntimeError,match='publication failed'): f.publish('2026-11')
    assert not (f.FORWARD/'2026-11.receipt.json').exists()
    f.publish('2026-11')
    assert path.read_bytes()==original
    assert f.read(f.FORWARD/'2026-11.receipt.json')['published_at_utc']=='2026-11-30T12:00:00+00:00'


def test_mark_uses_frozen_history_even_when_fresh_provider_revises_it(monkeypatch):
    bars=panel(); d=date(2026,11,30); rec=f.read(log(bars,d))
    receipt('2026-11',at(d))
    monkeypatch.setattr(f,'remote_log',lambda *_: at(d))
    fresh=bars.loc[:'2026-12-01'].copy()
    fresh.loc[:'2026-11-30',:]*=2
    state=f.mark_month('2026-11',fresh,now=at(date(2026,12,1)))
    c,o,v=bars['Close'],bars['Open'],bars['Volume']
    b,_,_=make_selectors(c,v)
    expected=simulate_rebalanced(c,o,point_in_time_adv(c,v,[d]),[d],select=b,
                                  cost_model=CostModel(brokerage_per_trade=0),budget=f.BUDGET,
                                  spread_bps=30,prior_close_carry=True)
    assert state['accounts']['basket']['equity']==pytest.approx(expected['final_equity'],rel=1e-12)


def test_refuses_out_of_order_mark_and_unrelated_publication(monkeypatch):
    with pytest.raises(ValueError,match='mark 2026-11 first'):
        f.mark_month('2026-12',pd.DataFrame())
    monkeypatch.setattr(f,'git',lambda *args: 'main' if args[0]=='branch' else 'unrelated.py')
    with pytest.raises(ValueError,match='unrelated'):
        f.publication_guard('2026-11')
