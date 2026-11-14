#!/usr/bin/env python3
"""Source-verified overlap review; annotations only, no candidate or graph mutation."""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,os,tempfile
from collections import Counter
from pathlib import Path

DECISIONS={"KEEP_LEFT_ONLY","KEEP_RIGHT_ONLY","KEEP_BOTH"}
KEEP_TYPE={}
KEEP_BOTH={}
def add(a,av,b,bv,keep,rule):
    KEEP_TYPE[frozenset(((a,av),(b,bv)))]=(keep,rule)
def both(a,av,b,bv,rule):
    KEEP_BOTH[frozenset(((a,av),(b,bv)))]=rule

for x in ("补法","泻法","补泻"):
    add("ACUPUNCTURE_TECHNIQUE",x,"SYNDROME",x,"ACUPUNCTURE_TECHNIQUE","CTX_TECHNIQUE_NOT_SYNDROME_V1")
add("ACUPUNCTURE_TECHNIQUE","补泻","SYNDROME","补泻的","ACUPUNCTURE_TECHNIQUE","CTX_TECHNIQUE_NOT_SYNDROME_V1")
for x in ("刺入穴","刺取穴","刺穴","刺这些穴"):
    add("ACUPUNCTURE_TECHNIQUE","针刺","ACUPOINT",x,"ACUPUNCTURE_TECHNIQUE","CTX_ACUPOINT_FRAGMENT_V1")
for theory,symptoms in {"上焦":("上焦","他上","他上焦","在上","在上焦"),"中焦":("中焦","因为中","因为中焦","因为中焦寒","因为中焦寒湿","在中","在中焦"),"下焦":("下焦",)}.items():
    for term in symptoms:
        add("CLASSICAL_THEORY",theory,"SYMPTOM",term,"CLASSICAL_THEORY","CTX_REGION_PHRASE_NOT_SYMPTOM_V1")
for theory,terms in {
 "上焦":("上焦",),"中焦":("中焦","中焦的"),"下焦":("下焦","下焦有","下焦阴"),
 "十二经脉":("十二经脉",),"卫气":("卫气","卫气昼","卫气昼行","卫气昼行于","卫气昼行于阳","卫气的","卫气的时","卫气的时间"),
 "清阳":("清阳","清阳的"),"营气":("营气","营气的")}.items():
    for term in terms:
        add("CLASSICAL_THEORY",theory,"SYNDROME",term,"CLASSICAL_THEORY","CTX_THEORY_TERM_NOT_SYNDROME_FRAGMENT_V1")
for term in ("与针","与针灸","再加上针"):
    add("HERB",term,"ACUPUNCTURE_TECHNIQUE","针灸","ACUPUNCTURE_TECHNIQUE","CTX_NON_HERB_GRAMMAR_FRAGMENT_V1")
for term in ("以治头","以治头痛"):
    add("HERB",term,"SYMPTOM","头痛","SYMPTOM","CTX_NON_HERB_GRAMMAR_FRAGMENT_V1")
add("HERB","可以治疗气","SYMPTOM","气喘","SYMPTOM","CTX_NON_HERB_GRAMMAR_FRAGMENT_V1")
add("FORMULA","都有腹","SYMPTOM","腹痛","SYMPTOM","CTX_NON_FORMULA_GRAMMAR_FRAGMENT_V1")
for symptom,tech in (("针刺","针刺"),("针刺放","放血"),("针刺放血","放血"),("使用放","放血"),("就针","针刺"),("就针刺","针刺"),("就针刺足","针刺"),("应针","针刺"),("应针刺","针刺"),("应针刺足","针刺"),("应针刺足太","针刺"),("我们针","针灸"),("我们针灸","针灸")):
    add("SYMPTOM",symptom,"ACUPUNCTURE_TECHNIQUE",tech,"ACUPUNCTURE_TECHNIQUE","CTX_PROCEDURE_NOT_SYMPTOM_FRAGMENT_V1")
for term in ("针刺放","针刺放血","刺痛"):
    add("SYMPTOM",term,"ACUPUNCTURE_TECHNIQUE","针刺","ACUPUNCTURE_TECHNIQUE","CTX_PROCEDURE_NOT_SYMPTOM_FRAGMENT_V1")
add("TREATMENT","中针","ACUPUNCTURE_TECHNIQUE","针刺","ACUPUNCTURE_TECHNIQUE","CTX_PROCEDURE_NOT_TREATMENT_FRAGMENT_V1")
add("CLASSICAL_THEORY","气街","ACUPOINT","气街穴","ACUPOINT","CTX_FULL_ACUPOINT_NAME_V1")
add("CLASSICAL_THEORY","十二经脉","PULSE","脉见","CLASSICAL_THEORY","CTX_MERIDIAN_PHRASE_NOT_PULSE_V1")
for term in ("中焦","中焦药"):
    add("CLASSICAL_THEORY","中焦","TREATMENT",term,"CLASSICAL_THEORY","CTX_REGION_TERM_NOT_TREATMENT_V1")
for term,theory in (("人的上","上焦"),("人的上焦","上焦"),("十二","十二经脉"),("十二经","十二经脉"),("阳的卫","卫气")):
    add("SYNDROME",term,"CLASSICAL_THEORY",theory,"CLASSICAL_THEORY","CTX_GRAMMAR_FRAGMENT_NOT_SYNDROME_V1")
for term in ("灸足","灸足三"):
    add("TREATMENT",term,"ACUPOINT","足三里穴","ACUPOINT","CTX_TREATMENT_PREFIX_FRAGMENT_V1")
add("SYNDROME","全头","SYMPTOM","头痛","SYMPTOM","CTX_INCOMPLETE_SYNDROME_FRAGMENT_V1")
both("ACUPUNCTURE_TECHNIQUE","艾灸","TREATMENT","艾灸","CTX_KEEP_DISTINCT_TECHNIQUE_AND_TREATMENT_V1")
both("TREATMENT","灸足三里","ACUPOINT","足三里穴","CTX_KEEP_DISTINCT_TREATMENT_AND_POINT_V1")
both("CLASSICAL_THEORY","下焦","SYNDROME","下焦阴实","CTX_KEEP_REGION_AND_FULL_PATTERN_V1")
both("CLASSICAL_THEORY","下焦","SYNDROME","下焦有热","CTX_KEEP_REGION_AND_FULL_PATTERN_V1")
both("SYNDROME","全头痛","SYMPTOM","头痛","CTX_KEEP_FULL_PATTERN_AND_SYMPTOM_V1")
both("SYNDROME","风寒咳嗽","SYMPTOM","咳嗽","CTX_KEEP_FULL_PATTERN_AND_SYMPTOM_V1")

def digest(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()
def validate(row,kind,line):
    loc=(row["document"],row["source_sha256"],row["tree_position"],row.get("block_id",""))
    if row["unit_id"]!=digest("\0".join(loc)): raise ValueError(f"row {line}: unit/source locator mismatch")
    if kind=="entity":
        if row["pair_id"]!=f'{row["unit_id"]}:{row["left_mention_id"]}:{row["right_mention_id"]}': raise ValueError(f"row {line}: pair id mismatch")
        lo,hi,txt=int(row["context_start"]),int(row["context_end"]),row["context_text"]
        if lo<0 or hi-lo!=len(txt): raise ValueError(f"row {line}: invalid evidence bounds")
        suffix="text"
    else:
        lo,hi,txt=int(row["evidence_start"]),int(row["evidence_end"]),row["evidence_text"]
        if lo<0 or hi-lo!=len(txt): raise ValueError(f"row {line}: invalid evidence bounds")
        identity=[row["unit_id"],*loc,[row["left_type"],row["left_candidate_id"],int(row["left_start"]),int(row["left_end"])],[row["right_type"],row["right_candidate_id"],int(row["right_start"]),int(row["right_end"])]]
        if row["pair_id"]!=digest(json.dumps(identity,ensure_ascii=False,separators=(",",":"))): raise ValueError(f"row {line}: typed occurrence pair id mismatch")
        suffix="term"
    for side in ("left","right"):
        a,b=int(row[side+"_start"]),int(row[side+"_end"])
        if not lo<=a<b<=hi or txt[a-lo:b-lo]!=row[side+"_"+suffix]: raise ValueError(f"row {line}: {side} text/offset mismatch")

def decide_entity(r):
    types={r["left_type"],r["right_type"]}
    if r["overlap_kind"] not in {"nested_cross_type_entity","nested_formula_herb_entity"}: return None
    if types=={"ORGAN","SYNDROME"}: return "KEEP_BOTH","ENTITY_ORGAN_AND_FULL_SYNDROME_LAYERS_V1"
    keep="FORMULA" if types=={"FORMULA","ORGAN"} else "HERB" if types=={"HERB","ORGAN"} else None
    if not keep: return None
    k="left" if r["left_type"]==keep else "right"; o="right" if k=="left" else "left"
    ks,ke=int(r[k+"_start"]),int(r[k+"_end"]); os_,oe=int(r[o+"_start"]),int(r[o+"_end"])
    if not ks<=os_<oe<=ke or (ks==os_ and oe==ke): return None
    rule="ENTITY_ORGAN_CHARACTER_INSIDE_FORMULA_NAME_V1" if keep=="FORMULA" else "ENTITY_ORGAN_CHARACTER_INSIDE_HERB_NAME_V1"
    return ("KEEP_LEFT_ONLY" if k=="left" else "KEEP_RIGHT_ONLY"),rule

def decide_contextual(r):
    pair=frozenset(((r["left_type"],r["left_term"]),(r["right_type"],r["right_term"])))
    if pair in KEEP_BOTH: return "KEEP_BOTH",KEEP_BOTH[pair]
    item=KEEP_TYPE.get(pair)
    if not item: return None
    keep,rule=item; sides=[s for s in ("left","right") if r[s+"_type"]==keep]
    if len(sides)!=1: return None
    return ("KEEP_LEFT_ONLY" if sides[0]=="left" else "KEEP_RIGHT_ONLY"),rule

def review(source,out,report,kind):
    if source.resolve()==out.resolve(): raise ValueError("output must differ from source")
    opener=gzip.open if source.suffix==".gz" else open
    with opener(source,"rt",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f); fields=list(reader.fieldnames or []); rows=list(reader)
    if not fields: raise ValueError("missing CSV header")
    seen=set(); rules=Counter(); prior=0
    for line,r in enumerate(rows,2):
        pid=r.get("pair_id","")
        if not pid or pid in seen: raise ValueError(f"row {line}: blank/duplicate pair ID")
        seen.add(pid); validate(r,kind,line)
        if r["review_status"]=="REVIEWED":
            if r["review_decision"] not in DECISIONS: raise ValueError(f"row {line}: invalid prior decision")
            prior+=1; continue
        if r["review_status"]!="UNREVIEWED" or r["review_decision"]: raise ValueError(f"row {line}: inconsistent review fields")
        result=decide_entity(r) if kind=="entity" else decide_contextual(r)
        if result:
            decision,rule=result
            if decision not in DECISIONS: raise ValueError("invalid internal decision")
            r["review_status"]="REVIEWED";r["review_decision"]=decision
            r["review_note"]=f"{rule}: exact evidence offsets checked; candidate and provenance retained; no relation inferred."
            rules[rule]+=1
    out.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=out.name+".",suffix=".tmp",dir=out.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
        os.replace(tmp,out)
    except Exception:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise
    status=Counter(r["review_status"] for r in rows)
    dec=Counter(r["review_decision"] for r in rows if r["review_status"]=="REVIEWED")
    result={"kind":kind,"input_rows":len(rows),"reviewed_by_rules":sum(rules.values()),"preexisting_reviewed_rows":prior,
            "review_status_counts":dict(sorted(status.items())),"review_decision_counts":dict(sorted(dec.items())),
            "rule_counts":dict(sorted(rules.items())),"remaining_unreviewed_rows":status.get("UNREVIEWED",0),
            "candidate_mutations":0,"relationship_inferences":0,"scope":"review annotations only; graph integration remains gated"}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--kind",choices=("entity","contextual"),required=True)
    p.add_argument("--input",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--report",type=Path,required=True)
    a=p.parse_args();review(a.input,a.output,a.report,a.kind)
if __name__=="__main__": main()
