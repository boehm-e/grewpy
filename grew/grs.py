import json
import os.path

from . import network
from . import utils
from .grew import JSON
from grew.graph import Graph

class ClauseList():
    def __init__(self,sort : str,*L):
        """
        sort in {"without", "pattern", "global"}
        L is a list of
         - ";" separated clauses or
         - a list of items
         - they will be concatenated
        """
        self.sort = sort
        self.items = tuple()
        for elt in L:
            if isinstance(elt,str):
                self.items += tuple(c.strip() for c in elt.split(";") if c.strip())
            else:
                self.items += tuple(elt)

    def json_data(self):
        return {self.sort : list(self.items)}

    @classmethod
    def from_json(cls, json_data : JSON) :
        k = list(json_data)[0]
        v = json_data[k]
        return cls(k,*v)

    def __str__(self):
        its = ";".join([str(x) for x in self.items])
        return f"{self.sort} {{{its}}}"

class Request():
    """
    lists of ClauseList
    """
    def __init__(self, *L):
        """
        L is either a list of
         - ClauseList or
         - (pattern) string or a
         - Request (for copies)
        """
        elts = tuple()
        for e in L:
            if isinstance(e,str):
                elts += (ClauseList("pattern", e),)
            elif isinstance(e,ClauseList):
                elts += (e,)
            elif isinstance(e,Request):
                elts += e.items
            else:
                raise ValueError(f"{e} cannot be used to build a Request")
        self.items = elts

    def without(self, *L):
        self.items += tuple(ClauseList("without", e) for e in L)
        return self

    @classmethod
    def from_json(cls,json_data):
        elts = [ClauseList.from_json(c) for c in json_data]
        return cls(*elts)

    def json_data(self):
        return [x.json_data() for x in self.items]

    def __str__(self):
        return "\n".join([str(e) for e in self.items])

class Command(list):
    def __init__(self, *L):
        super().__init__()
        for elt in L:
            if isinstance(elt,str):
                self += [t.strip() for t in elt.split(";") if t.strip()]
            elif isinstance(elt,list):
                self += elt

    def __str__(self):
        c = ";".join(self)
        return f"commands {{{c}}}"

    @classmethod
    def from_json(cls, json_data):
        return cls(*json_data)

class Rule():
    def __init__(self, request : Request, cmd_list : Command):
        self.request = request
        self.commands = cmd_list

    def json_data(self):
        p = self.request.json_data()
        return {"request" : p, "commands" : self.commands}

    def __str__(self):
        return f"{str(self.request)}\n{str(self.commands)}"

    @classmethod
    def from_json(cls,json_data):
        # print(json_data)
        reqs = Request.from_json(json_data["request"])
        cmds = Command.from_json(json_data["commands"])
        return cls(reqs,cmds)

class Package(dict):
    """
    dict mapping names to rule/package/strategies"""

    @classmethod
    def from_json(cls, json_data):
        res = Package._from_json(json_data)
        return cls(res)

    def _from_json(json_data):
        res = dict()
        for k,v in json_data.items():
            if isinstance(v,str):
                res[k] = v
            elif "decls" in v: #it is a package
                res[k] = Package.from_json(v["decls"])
            else:
                res[k] = Rule.from_json(v)
        return res

    def json_data(self):
        elts = dict()
        for k,v in self.items():
            elts[k] = v if isinstance(v,str) else v.json_data()
        return {"decls" : elts}

    def __str__(self):
        res = [f"strat {k} {{{self[k]}}}" for k in self.strategies()] +\
            [f"package {k} {{{str(self[k])}}}" for k in self.packages()] +\
            [f"rule {k} {{{str(self[k])}}}" for k in self.rules()]
        return "\n".join(res)

    def rules(self):
        return filter(lambda x: isinstance(self[x], Rule), self.__iter__())

    def packages(self):
        return filter(lambda x: isinstance(self[x], Package), self.__iter__())

    def strategies(self):
        return filter(lambda x: isinstance(self[x], str), self.__iter__())


class GRS(Package):

    def _load(data):
        """load data (either a filename or a json encoded string) within grew"""
        if os.path.isfile(data):
            req = {"command": "load_grs", "filename": data}
        else:
            req = {"command": "load_grs", "str": data}
        reply = network.send_and_receive(req)
        index = reply["index"]
        return index

    def _build(self):
        """ ensure that the GRS is loaded (and call Ocaml if needed)"""
        if not self.index:
            data = self.json_data()
            req = {"command": "load_grs", "json": data}
            reply = network.send_and_receive(req)
            index = reply["index"]
            self.index = index

    def __init__(self,args):
        """Load a grs stored in a file
        :param data: either a file name or a Grew string representation of a grs
        :or kwargs contains explicitly the parts of the grs
        :return: an integer index for latter reference to the grs
        :raise an error if the file was not correctly loaded
        """
        if isinstance(args,str):
            index = GRS._load(args)
            req = {"command": "json_grs", "grs_index": index}
            json_data = network.send_and_receive(req)
            res = Package._from_json(json_data["decls"])
            super().__init__(res)
            self.index = index
        elif isinstance(args, dict):
            super().__init__( args )
            self.index = 0

    def __str__(self):
        return super().__str__()

    def run(self, G, strat="main"):
        """
        Apply rs or the last loaded one to [gr]
        :param grs_data: a graph rewriting system or a Grew string representation of a grs
        :param G: the graph, either a str (in grew format) or a dict
        :param strat: the strategy (by default "main")
        :return: the list of rewritten graphs
        """
        self._build() # first ensure that the GRS is loaded in Ocaml
        req = {
            "command": "run",
            "graph": json.dumps(G.json_data()),
            "grs_index": self.index,
            "strat": strat
        }
        # print("---------------------")
        # print(req)
        # print("-------------------------")
        reply = network.send_and_receive(req)
        return [Graph(s) for s in reply]


    def __setitem__(self,x,v):
        self.index = 0
        super().__setitem__(x,v)