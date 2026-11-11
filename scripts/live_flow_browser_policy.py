"""Strict runtime policy and baseline controls, loaded as normal external JS."""
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def install(page, baseline=False):
    policy="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'"
    prefix="""window.flowPolicyViolations=[];
document.addEventListener('securitypolicyviolation',e=>window.flowPolicyViolations.push({directive:e.effectiveDirective,blocked:e.blockedURI,source:e.sourceFile,line:e.lineNumber}));
const flowStrictMeta=document.createElement('meta');flowStrictMeta.httpEquiv='Content-Security-Policy';flowStrictMeta.content=POLICY;document.head.append(flowStrictMeta);
const flowSentinel=document.createElement('i');flowSentinel.setAttribute('style','color:rgb(1, 2, 3)');document.body.append(flowSentinel);
window.flowStyleSentinel=getComputedStyle(flowSentinel).color!=='rgb(1, 2, 3)';flowSentinel.remove();
try{Function('return 1')();window.flowEvalSentinel=false;}catch(e){window.flowEvalSentinel=true;}
const FlowNativeWorker=window.Worker;window.flowWorkerCounts={created:0,terminated:0};
window.Worker=class extends FlowNativeWorker{constructor(...args){super(...args);this.flowTerminated=false;flowWorkerCounts.created++;}terminate(){if(!this.flowTerminated){this.flowTerminated=true;flowWorkerCounts.terminated++;}return super.terminate();}};
""".replace('POLICY',json.dumps(policy))
    page.route('**/static/visual-loader.js*',lambda route:route.fulfill(content_type='text/javascript',body=prefix+(ROOT/'static/visual-loader.js').read_text(encoding='utf-8')))
    if baseline:
        for name in ['topic-handoffs','maintenance-trace']:
            source=subprocess.run(['git','show',f'f6dffda:static/{name}.js'],cwd=ROOT,capture_output=True,check=True).stdout.decode('utf-8')
            page.route(f'**/static/{name}.js',lambda route,request,source=source:route.fulfill(content_type='text/javascript',body=source))


def verify(page):
    assert page.evaluate('flowStyleSentinel&&flowEvalSentinel'), 'The strict runtime sentinels must both be blocked'
    violations=page.evaluate('flowPolicyViolations')
    # The two deliberate sentinel violations are retained in the evidence.
    library=[v for v in violations if not ('/static/visual-loader.js' in v['source'] and v['blocked'] in ('inline','eval')) and not (v['source']=='http://local.adguard.org/' and v['blocked']=='eval')]
    # Windows AdGuard injects a probe independently of application assets. Its
    # blocked eval remains in evidence; it is not a library CSP relaxation.
    assert not library,library
    return violations


def verify_workers(page):
    counts=page.evaluate('flowWorkerCounts')
    assert counts['created']==counts['terminated'],counts
    return counts
