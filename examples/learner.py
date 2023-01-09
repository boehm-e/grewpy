import matplotlib.pyplot as plt
from sklearn import tree
from sklearn.tree import DecisionTreeClassifier
import sys, os, math
import numpy as np
import pickle
import re

sys.path.insert(0, os.path.abspath(os.path.join( os.path.dirname(__file__), "../"))) # Use local grew lib

from grewpy import Corpus, GRS, set_config
from grewpy import Request, Rule, Commands, Add_edge, GRSDraft, CorpusDraft, Graph

#type declaration
# 
def remove_rank(e):
    return tuple(sorted(list((k,v) for k,v in e.items() if k != "rank")))

def edge_equal_up_to_rank(e1,e2):
    return remove_rank(e1) == remove_rank(e2)

def diff(g1,g2):
    E1 = g1.triples()
    E1b = {(n,remove_rank(e),s) for (n,e,s) in E1 if "SPAN" not in e["1"]}
    E2 = g2.triples()
    E2b = {(n,remove_rank(e),s) for (n,e,s) in E2 if "SPAN" not in e["1"]}
    return np.array([len(E1b & E2b), len(E1b - E2b), len(E2b - E1b)])

def diff_corpus_rank(c1,c2):
    (common, left, right) = np.sum([diff(c1[sid],c2[sid]) for sid in c1], axis=0)
    precision = common / (common + left)
    recall = common / (common + right)
    f_measure = 2*precision*recall / (precision+recall)
    return {
        "common": common,
        "left": left,
        "right": right,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f_measure": round(f_measure, 3),
    }

class Observation:
    @staticmethod
    def _enumerate(obs, crit, L):
        if not obs:
            return
        if len(crit) == 1:
            for k in obs:
                yield (L+(k,), obs[k])
        else:
            for k in obs:
                yield from Observation._enumerate(obs[k], crit[1:],L + (k,))

    def __init__(self, obs, criterion):
        self.obs = {L : v for L,v in Observation._enumerate(obs, criterion, tuple())}

    def __iter__(self):
        return iter(self.obs)
    def __getitem__(self, k):
        return self.obs[k]
        

def cluster(corpus : Corpus, P : Request, cluster_criterion) -> Observation:
    """
    search for a link X -> Y with respect to pattern P in the corpus
    we build a cluster depending on X.upos and Y.upos
    """
    P1 = Request(P, f'e:X-> Y', 'e.rank="_"')
    c0 = corpus.count(P1, cluster_criterion + ["e.label"])
    if c0 == 0:
        return Observation({},None)
    obs = Observation(c0, cluster_criterion)
    W1 = Request(P).without(f"X -[^LEFT_SPAN|RIGHT_SPAN]-> Y")
    c1 = corpus.count(W1, cluster_criterion)
    if c1:
        clus = Observation(c1, cluster_criterion)
        for L in obs:
            if L in clus:
                obs[L][''] = clus[L]
    return obs

def anomaly(obs,  param):
    """
    return an observation and its probability if beyond base_threshold
    """
    s = sum(obs.values()) 
    for x in obs:
        if obs[x] > param["base_threshold"] * s and x:
            return x, obs[x]/s
    return None, None

def build_rules(base_pattern, rules : GRSDraft, corpus : Corpus, rule_name, rule_eval, param, cluster_criterion,rank_level=0):
    """
    search a rule adding an edge X -> Y, given a base_pattern  
    we build the clusters, then
    for each pair (X, upos=U1), (Y, upos=U2), we search for 
    some edge e occuring at least with probability base_threshold
    in which case, we define a rule R: 
    base_pattern /\ [X.upos=U1] /\ [Y.upos=U2] => add_edge X-[e]-Y
    """
    def crit_to_request(crit,val):
        if ".label" in crit:
            edge_name = re.match("(.*?).label", crit).group(1)
            clauses = []
            for it in val.split(","):
                a, b = it.split("=")
                clauses.append(f'{edge_name}.{a}="{b}"')
            return ";".join(clauses)
        return f"{crit}={val}"
    obslr = cluster(corpus, base_pattern, cluster_criterion)
    for L in obslr:
        x,p = anomaly(obslr[L], param)
        if x:
            extra_pattern = ";".join(crit_to_request(crit,val) for (crit,val) in zip(cluster_criterion,L))
            P = Request(base_pattern, extra_pattern)
            x = x.replace(f"rank=_",f'rank="{rank_level}"')
            c = Add_edge("X",x,"Y")
            R = Rule(P, Commands( c))
            rn = f"_{'_'.join(L)}_{rule_name}"
            rules[rn] = R
            rule_eval[rn] = (x,p)

def rank0(corpus : Corpus, param) -> GRSDraft:
    """
    build all rank 0 rules. They are supposed to connect words at distance 1
    """
    rules = GRSDraft()
    rule_eval = dict() #eval of the rule, same keys as rules
    build_rules("X[];Y[];X<Y", rules, corpus, "lr", rule_eval, param, ["X.upos","Y.upos"])
    build_rules("X[];Y[];Y<X", rules, corpus, "rl", rule_eval, param, ["X.upos","Y.upos"])
    return rules, rule_eval

def span_rules(corpus, param):
    rules = GRSDraft()
    rule_eval = dict()
    span = "LEFT_SPAN|RIGHT_SPAN"
    build_rules(f"X[];Y[];X -[{span}]->Z;Z<Y", rules, corpus, "span_Zlr", rule_eval, param, ["X.upos","Y.upos"])
    build_rules(f"X[];Y[];X -[{span}]->Z;Y<Z", rules, corpus, "span_Zrl", rule_eval, param, ["X.upos","Y.upos"])
    build_rules(f"X[];Y[];Y -[{span}]->T;X<T",rules, corpus, "span_Tlr", rule_eval, param, ["X.upos","Y.upos"])
    build_rules(f"X[];Y[];Y -[{span}]->T;T<X", rules, corpus, "spanT_rl", rule_eval, param, ["X.upos","Y.upos"])
    build_rules(f"X[];Y[];Y -[{span}]->T;X-[{span}]->Z;Z<T", rules, corpus, "span_ZTlr", rule_eval, param, ["X.upos","Y.upos"])
    build_rules(f"X[];Y[];Y -[{span}]->T;X-[{span}]->Z;T<Z", rules,
                corpus, "span_ZTrl", rule_eval, param, ["X.upos", "Y.upos"])
    return rules, rule_eval


def nofilter(k,v,param):
    """
    avoid to use meaningless features/feature values
    return True if k=feature,v=feature value can be used for classification
    """
    if len(v) > param["feat_value_size_limit"] or len(v) == 1:
        return False
    if k in param["skip_features"]:
        return False
    return True

def get_tree(X,y,param):
    """
    build a decision tree based on observation X,y
    given hyperparameter within param
    """
    if not X or not len(X[0]):
        return None
    if max(y) == 0:
        return None
    clf = DecisionTreeClassifier(max_depth=param["max_depth"], 
                                max_leaf_nodes=max(y)+param["number_of_extra_leaves"],
                                min_samples_leaf=param["min_samples_leaf"], 
                                criterion="gini")
    clf.fit(X, y)
    return clf

def fvs(matchings, corpus, param):
    """
    return the set of (Z,feature,values) of nodes Z=X, Y in the matchings
    within the corpus. param serves to filter meaningful features values
    """
    features = {'X' : dict(), 'Y':dict()}
    for m in matchings:
        graph = corpus[m["sent_id"]]
        nodes = m['matching']['nodes']
        for n in {'X','Y'}:
            N = graph[nodes[n]] #feature structure of N
            for k,v in N.items():
                if k not in features[n]:
                    features[n][k] = set()
                features[n][k].add(v)
    features = [(n,k,fv) for n in features for k,v in features[n].items() if nofilter(k,v,param) for fv in v]
    return features

def create_classifier(matchings, pos, corpus, param):
    """
    builds a decision tree classifier
    matchings: the matching on the two nodes X, Y
    we compute the class mapping (feature values of X, feature values of Y) to the edge between X and Y
    pos: maps a triple (node=X or Y, feature=Gen, feature_value=Fem) to a column number
    corpus serves to get back graphs
    param contains hyperparameter
    """
    X, y1,y = list(), dict(), list()
    #X: set of input values, as a list of (0,1)
    #y: set of output values, an index associated to the edge e
    #the absence of an edge has its own index
    #y1: the mapping between an edge e to some index
    for m in matchings:
        #each matching will lead to an obs which is a list of 0/1 values 
        graph = corpus[m["sent_id"]]
        nodes = m['matching']['nodes']
        obs = [0]*len(pos)
        for n in nodes:
            feat = graph[nodes[n]]
            for k, v in feat.items():
                if (n, k, v) in pos:
                    obs[pos[(n, k, v)]] = 1
        e = graph.edge(nodes['X'], nodes['Y'])
        if e not in y1:
            y1[e] = len(y1)
        y.append(y1[e])
        X.append(obs)
    
    return get_tree(X,y,param), {y1[i] : i for i in y1}


def find_classes(clf, param):
    """
    given a decision tree, extract "interesting" branches
    the output is a dict mapping the node_index to its branch
    a branch is the list of intermediate constraints = (7,1,8,0,...)
    that is feature value 7 has without clause whereas feature 8 is positive 
    """
    def branches(pos, tree, current, acc, threshold):
        if tree.feature[pos] >= 0:
            if tree.impurity[pos] < threshold:
                acc[pos] = current
                return
            #there is a feature
            if tree.children_left[pos] >= 0:
                #there is a child
                left = current + ((tree.feature[pos],1),)
                branches(tree.children_left[pos], tree, left, acc, threshold)
            if tree.children_right[pos] >= 0:
                right = current + ((tree.feature[pos], 0),)
                branches(tree.children_right[pos], tree, right, acc, threshold)
            return 
        else:
            if tree.impurity[pos] < threshold:
                acc[pos] = current
    tree = clf.tree_
    acc = dict()
    branches(0, tree, tuple(), acc, param["node_impurity"])
    return acc


def refine_rule(R, corpus, param):
    """
    Takes a request R, tries to find variants
    
    the result is the list of rules that refine pattern R
    for DEBUG, we return the decision tree classifier
    """
    res = []
    matchings = corpus.search(R)
    fpat = fvs(matchings, corpus, param) #the list of all feature values 
    pos = {fpat[i]: i for i in range(len(fpat))}
    clf, y1 = create_classifier(matchings, pos, corpus, param)
    if clf:
        branches = find_classes(clf, param) #extract interesting branches
        for node in branches:
            branch=branches[node]
            request = Request(R) #builds a new Request
            for feature_index, negative in branch:
                n, feat, feat_value = fpat[feature_index]
                feat_value = feat_value.replace('"', '\\"')
                if negative:
                    request = request.without(f'{n}[{feat}="{feat_value}"]')
                else:
                    request.append("pattern",f'{n}[{feat}="{feat_value}"]')
            e = y1[ clf.tree_.value[node].argmax()]
            if e: #here, e == None if there is no edges X -> Y
                rule = Rule(request, Commands(Add_edge("X",e,"Y")))
                res.append(rule)
    return res, clf
    """
    import pickle
        tree.plot_tree(clf)
        #x = input("keep")
        if x:  
            pickle.dump(clf, open("hum.pickle", "wb"))
            x = 0
        """

def refine_rules(Rs, rule_eval,corpus, param,debug=False):
    """
    as above, but applies on a list of rules
    and filter only "correct" rules, see `param`
    return the list of refined version of rules Rs
    """
    Rse = GRSDraft()
    for rule_name in Rs.rules():
        R = Rs[rule_name]
        if rule_eval[rule_name][1] < param["valid_threshold"]:
            new_r, clf = refine_rule(R.request, corpus, param)
            if len(new_r) >= 1:
                cpt = 1
                if debug:
                    print("--------------------------replace")
                    print(R)
                for r in new_r:
                    if debug:
                        print("by : ")
                        print(r)
                    Rse[f"{rule_name}_enhanced{cpt}"] = r
                    cpt += 1
        else:
            Rse[rule_name] = R
    return Rse

def corpus_span(corpus):
    """
    add span edges to graphs in corpus
    """
    def add_span(g):
        N = len(g)
        left,right = {i : i for i in g }, {i : i for i in g}
        todo = [i for i in g]
        for i in g:
            if i not in g.sucs:
                g.sucs[i] = []
        while todo:
            n = todo.pop(0)
            for s,_ in g.sucs[n]:
                if g.lower(left[s],left[n]):
                    left[n] = left[s]
                    todo.append(n)
                if g.greater(right[s],right[n]):
                    right[n] = right[s]
                    todo.append(n)
        for i in g:
            g.sucs[i].append((left[i],{'1':'LEFT_SPAN'}))
            g.sucs[i].append((right[i],{'1':'RIGHT_SPAN'}))
        return g
            
    draft = CorpusDraft(corpus)
    return Corpus(draft.map(add_span))

def corpus_remove_edges(corpus):
    """
    create a corpus based on *corpus* whose graphs have no edges
    """
    def clear_edges(g):
        del g.sucs
        return g
    return Corpus(CorpusDraft(corpus).map(clear_edges))

def corpus_remove_edges_but_span(corpus):
    """
    remove edges but spans within corpus
    """
    def is_span(e):
        return "SPAN" in e.get("1","")
        
    def clear_but_span(g):
        for n in g.sucs:
            g.sucs[n] = [(s,e) for (s,e) in g.sucs[n] if is_span(e)]
        return (g)
    return Corpus(CorpusDraft(corpus).map(clear_but_span))

def get_best_solution(corpus_gold, corpus_empty_edges, grs):
    """
    grs is a GRSDraft
    return the best solution using the grs with respect to the gold corpus
    the grs does not need to be confluent. We take the best solution with 
    respect to the f-score
    """
    def f_score(t):
        return t[0]/math.sqrt((t[0]+t[1])*(t[0]*t[2])+1e-20)

    corpus_draft = CorpusDraft(corpus_empty)
    for sid in corpus_gold:
        gs = grs.run(corpus_empty_edges[sid],'main')
        best_fscore = 0
        for g in gs:
            fs = f_score(g.diff(corpus_gold[sid]))
            if  fs > best_fscore:
                best_fscore = fs
                corpus_draft[sid] = g
    return corpus_draft

def init_rank(corpus):
    def add_null_rank(e):
        if isinstance(e,str):
            return {"1": e, "rank":"_"}
        e["rank"] ="_"
        return e
    def add_rank(g):
        for n in g:
            if n in g.sucs:
                g.sucs[n] = [(m,add_null_rank(e)) for (m,e) in g.sucs[n]] 
        return g
    return Corpus(CorpusDraft(corpus).map(add_rank))

def update_gold_rank(corpus_gold, computed_corpus):
    """
    build a copy of corpus_gold but with a rank update
    """
    new_gold = CorpusDraft(corpus_gold)
    for sid in new_gold:
        g_gold = new_gold[sid]
        g_new = computed_corpus[sid]
        for n in g_gold.sucs:
            if n in g_new:
                new_sucs = []
                for (m,e) in g_gold.sucs[n]:
                    e_new = g_new.edge(n,m)
                    if isinstance(e_new, str):
                        st = [a.split("=") for a in e_new.split(",")]
                        e_new = {x[0].strip() : x[1].strip() for x in st}
                        
                    if e_new and edge_equal_up_to_rank(e,e_new):
                        new_sucs.append((m,e_new))
                    else:
                        new_sucs.append((m,e))
                g_gold.sucs[n] = new_sucs
    return new_gold 

def rank_n_plus_one(corpus_gold, param, rank_n):
    """
    build rules for corpus
    """
    rules = GRSDraft()
    rule_eval = dict()  # eval of the rule, same keys as rules
    corpus = Corpus(corpus_gold)
    nodes = ['f:X -> Z', 'f:Y -> Z','f:Z->X','f:Z->Y']
    ordres = ['X<Y','X>Y','Z<Y','Z>Y','X<Z','X>Z']
    for ns in nodes:
        for o in ordres:
            pat = f'X[];Y[];{ns};{o};f.rank="{rank_n}"'
            build_rules(pat, rules, corpus, '1lr', rule_eval, param, ["X.upos","Y.upos","f.label"], rank_n+1)
    return rules, rule_eval


if __name__ == "__main__":
    set_config("sud")
    param = {
        "base_threshold": 0.25,
        "valid_threshold": 0.90,
        "max_depth": 4,
        "min_samples_leaf": 5,
        "max_leaf_node": 5,  # unused see DecisionTreeClassifier.max_leaf_node
        "feat_value_size_limit": 10,
        "skip_features": ['xpos', 'upos', 'SpaceAfter'],
        "node_impurity" : 0.2,
        "number_of_extra_leaves" : 5
    }
    if len(sys.argv) > 1:
        corpus_file = sys.argv[1]
    else:
        corpus_file = "examples/resources/fr_pud-sud-test.conllu"
    
    corpus_gold = Corpus (corpus_file)
    corpus_gold = init_rank(corpus_gold) #rank label on edges
    corpus_gold = corpus_span(corpus_gold)# span
    corpus_empty = corpus_remove_edges_but_span(corpus_gold)
    
    R0, rule_eval = rank0(corpus_gold, param)
    A = corpus_gold.count(Request("X<Y;e:X->Y").without("e.1=LEFT_SPAN").without("e.1=RIGHT_SPAN"), [])
    A += corpus_gold.count(Request("Y<X;e:X->Y").without(
        "e.1=LEFT_SPAN").without("e.1=RIGHT_SPAN"), [])
    print("---target----")
    print(
        f'number of edges within corpus {corpus_gold.count(Request("e:X->Y").without("e.1=LEFT_SPAN").without("e.1=RIGHT_SPAN"),[])}')
    print(f"number of adjacent relations: {A}")
    print(f"adjacent rules before refinement: len(R0) = {len(R0)}")
    R0_test = GRS(R0.safe_rules().onf()) 
    c = get_best_solution(corpus_gold, corpus_empty, R0_test) 
    print(diff_corpus_rank(c,corpus_gold))

    R0e = refine_rules(R0, rule_eval, corpus_gold, param)
    print(f"after refinement: len(R0e) = {len(R0e)}")
    R0e_test = GRS(R0e.safe_rules().onf())
    c = get_best_solution(corpus_gold, corpus_empty, R0e_test)
    print(diff_corpus_rank(c,corpus_gold))

    Rs0, r0eval = span_rules(corpus_gold,param)
    print(f"span rules: len(Rs0) = {len(Rs0)}")

    Rs0e = refine_rules(Rs0, r0eval, corpus_gold, param)
    Rs0e_t = GRS(Rs0e.safe_rules().onf())
    print(f"span rules after refinement {len(Rs0e)}")
    c = get_best_solution(corpus_gold, corpus_empty, Rs0e_t)
    print(diff_corpus_rank(c,corpus_gold))

    #union of adjacent rules and span rules
    R0f = GRSDraft(R0e | Rs0e)
    R0f_t = GRS(R0f.safe_rules().onf())
    c = get_best_solution(corpus_gold, corpus_empty, R0f_t)
    print(diff_corpus_rank(c,corpus_gold))

    corpus_gold_after_rank0 = update_gold_rank(corpus_gold, c)
    
    #(corpus_gold_after_rank0, R0f) = pickle.load(open("hum.pickle","rb"))
    #R0f_t = GRS(R0f.safe_rules().onf())
    computed_corpus_after_rank0 = get_best_solution(corpus_gold, corpus_empty, R0f_t)

    R1_0, R10eval  = rank_n_plus_one(corpus_gold_after_rank0,param, 0)
    R1e_0 = refine_rules(R1_0, R10eval, corpus_gold, param)
    R1e_0 = GRSDraft({re.sub("[.,=]","",r) : v for (r,v) in R1e_0.items()})
    Rx = R1e_0.safe_rules()
    R1e_0_t = GRS(Rx.onf())
    computed_corpus_after_rank1 = get_best_solution(corpus_gold_after_rank0, computed_corpus_after_rank0, R1e_0_t)
    print("Rank 1 rules")
    print(len(R1e_0))
    print((diff_corpus_rank(computed_corpus_after_rank1,corpus_gold)))

    corpus_gold_after_rank1 = update_gold_rank(corpus_gold,computed_corpus_after_rank1)
    R2_0, R2eval = rank_n_plus_one(corpus_gold_after_rank1, param, 1)
    R2e_0 = refine_rules(R2_0, R2eval, corpus_gold, param)
    R2e_0 = GRSDraft({re.sub("[.,=]", "", r): v for (r, v) in R2e_0.items()})
    Rx = R2e_0.safe_rules()
    R2e_0_t = GRS(Rx.onf())
    computed_corpus_after_rank2 = get_best_solution(corpus_gold_after_rank1, computed_corpus_after_rank1, R2e_0_t)
    print("Rank 2 rules")
    print(len(R2e_0))
    print((diff_corpus_rank(computed_corpus_after_rank2, corpus_gold)))

    corpus_gold_after_rank2 = update_gold_rank(
        corpus_gold, computed_corpus_after_rank2)
    R3_0, R3eval = rank_n_plus_one(corpus_gold_after_rank2, param, 2)
    R3e_0 = refine_rules(R3_0, R3eval, corpus_gold, param)
    R3e_0 = GRSDraft({re.sub("[.,=]", "", r): v for (r, v) in R3e_0.items()})
    Rx = R3e_0.safe_rules()
    R3e_0_t = GRS(Rx.onf())
    computed_corpus_after_rank3 = get_best_solution(corpus_gold_after_rank2, computed_corpus_after_rank2, R3e_0_t)
    print("Rank 3 rules")
    print(len(R3e_0))
    print((diff_corpus_rank(computed_corpus_after_rank3, corpus_gold)))


