"""
Grew module: anything you want to talk about graphs
"""
import os.path
import re
import copy
import tempfile
import json

from grew.utils import GrewError
from grew.network import send_and_receive
from grew import utils

''' interfaces'''
class Fs_edge(dict):
    def __init__(self,data):
        if isinstance(data,str):
            super().__init__({"1": data})
        elif isinstance(data, dict):
            super().__init__(data)
        else:
            raise ValueError(f"data is not a feature structure {data}")

    def __str__(self):
        return (",".join([f"{f}={v}" for (f,v) in self.items()]))

    def __hash__(self):
        return (hash (str(self)))

class Graph():
    """
    a dict mapping node keys to feature structure
    with an extra dict mapping node keys to successors (pair of edge feature,node key)
    """
    def __init__(self,data=None):
        """
        :param data: either None=>empty graph
        a string: a json representation => read json
        a json-decoded representation => fill with json
        an oterh graph => copy the dict
        :return: a graph
        """
        if data is None:
            self.features = dict()
            self.sucs = dict()  # ??? initaliser à []
            self.meta = dict()
            self.order = []
        elif isinstance(data,str):
            #either json or filename
            try:
                data_json = json.loads(data)
                self.__of_dict(data_json)
            except json.decoder.JSONDecodeError:
                pass # TODO load file
        elif isinstance(data, Graph):
            self.features = dict(data.features)
            self.sucs = dict(data.sucs)
            self.meta = dict(data.meta)
            self.order = list(data.order)
        elif isinstance(data, dict):
            self.__of_dict(data)

    def __of_dict(self,data_json):
        self.features = data_json["nodes"]
        self.sucs = dict()
        for edge in data_json.get("edges", []):
            utils.map_append (self.sucs, edge["src"], (edge["tar"], Fs_edge(edge["label"]))) # TODO gestion des "label" implicite
        self.meta = data_json.get("meta", dict())
        self.order = data_json.get("order", list())

    def __len__(self):
        return len(self.features)

    def __getitem__(self, nid):
        return (self.features[nid])

    def __iter__(self):
        return iter(self.features)

    def suc(self, nid):
        #return self.sucs[nid] if nid in self.sucs else
        return self.sucs.get(nid, [])

    def to_dot(self): # TODO fix it
        """
        return a string in dot/graphviz format
        """
        s = 'digraph G{\n'
        for n,fs in self.features.items():
            s += f'{n}[label="'
            label = ["%s:%s" % (f,v.replace('"','\\"')) for f, v in fs.items()]
            s += ",".join(label)
            s += '"];\n'
        s += "\n".join([f'{n} -> {m}[label="{e}"];' for n,suc in self.sucs.items() for e,m in suc])
        return s + '\n}'

    def json_data(self):
        nds = {c:self[c] for c in self.features}
        edg_list = []
        for n in self.sucs:
            for (e,s) in self.sucs[n]:
                if len(s.keys()) == 1 and '1' in s.keys():
                    s = s["1"]
                edg_list.append({"src":f"{n}", "label":s,"tar":f"{e}"})
        return {"nodes" : nds, "edges" : edg_list, "order": self.order }

    def __str__(self):
        return f"({str(self.features)}, {str(self.sucs)})" # TODO order, meta

    def to_conll(self):
        """
        return a CoNLL string for the given graph
        """
        data = self.json()
        req = {"command": "conll_graph", "graph": data}
        reply = send_and_receive(req)
        return reply

    def triples(self):
        return set((n, e, s) for n in self.sucs for e,s in self.sucs[n])