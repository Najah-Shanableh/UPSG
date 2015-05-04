import numpy as np

from ..stage import RunnableStage, MetaStage
from ..uobject import UObject, UObjectPhase
from ..utils import np_sa_to_nd
from ..pipeline import Pipeline
from .identity import Identity
from .split import SplitColumns

from numpy.lib.recfunctions import merge_arrays

class ApplyToSelectedCols(MetaStage):

    """
    Applies a given transformation only to the selected columns.

    Input keys and output keys are identical to those of the selected transform

    Parameters
    ----------
    col_names : list of str
        Names of the columns to which the transform Stage will be supplied
    stage_cls : upsg.stage.Stage class
        the class of the transform Stage 
    *args 
        init args for the Stage
    **kwargs 
        init kwargs for the stage

    """

    class __Merge(RunnableStage):
        @property
        def input_keys(self): 
            return ['in0', 'in1']

        @property
        def output_keys(self):
            return ['out']

        def run(self, outputs_requested, **kwargs):
            in0 = kwargs['in0'].to_np()
            in1 = kwargs['in1'].to_np()
            out = merge_arrays((in0, in1), flatten=True)
            uo_out = UObject(UObjectPhase.Write)
            uo_out.from_np(out)
            return {'out': uo_out}

    def __init__(self, col_names, stage_cls, *args, **kwargs):
        p = Pipeline()
        self.__pipeline = p
        trans_node = p.add(stage_cls(*args, **kwargs))
        trans_node_in_keys = list(trans_node.input_keys)
        in_node = p.add(Identity(trans_node_in_keys))
        correspondence = in_node.get_stage().get_correspondence()
        split_node = p.add(SplitColumns(col_names))
        # TODO we assume that our Stage has one of these keys, which is bad
        for in_key in ('in', 'X_train'):
            if in_key in trans_node_in_keys:
                in_node[correspondence[in_key]] > split_node['in']
                split_node['out'] > trans_node[in_key]
                trans_node_in_keys.remove(in_key)
                break
        for in_key in trans_node_in_keys:
            in_node[correspondence[in_key]] > trans_node[in_key]
        trans_node_out_keys = list(trans_node.output_keys)
        merge_node = p.add(self.__Merge())
        out_node = p.add(Identity(output_keys=trans_node_out_keys))
        correspondence = out_node.get_stage().get_correspondence(False)
        for out_key in ('out', 'X_new'):
            if out_key in trans_node_out_keys:
                trans_node[out_key] > merge_node['in0']
                split_node['complement'] > merge_node['in1']
                merge_node['out'] > out_node[correspondence[out_key]]
                trans_node_out_keys.remove(out_key)
        for out_key in trans_node_out_keys:
            trans_node[out_key] > out_node[correspondence[out_key]]
        self.__pipeline = p
        self.__in_node = in_node
        self.__out_node = out_node

    @property
    def input_keys(self):
        return self.__in_node.input_keys

    @property
    def output_keys(self):
        return self.__out_node.output_keys

    @property
    def pipeline(self):
        return (self.__pipeline, self.__in_node, self.__out_node)
