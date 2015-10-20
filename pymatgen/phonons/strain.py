import warnings
import sys
import unittest
import pymatgen
from pymatgen.io.vasp import Poscar
from pymatgen.io.vasp import Poscar
from pymatgen.io.vasp import Vasprun
from pymatgen.io.cif import CifWriter
from pymatgen.io.cif import CifParser
from pymatgen.core.lattice import Lattice
from pymatgen.core.structure import Structure
from pymatgen.transformations.standard_transformations import *
from pymatgen.phonons import voigt_map
from pymatgen.phonons.tensors import SQTensor
import warnings
import numpy as np
import os

__author__ = "Maarten de Jong"
__copyright__ = "Copyright 2012, The Materials Project"
__credits__ = "Mark Asta, Anubhav Jain"
__version__ = "1.0"
__maintainer__ = "Maarten de Jong"
__email__ = "maartendft@gmail.com"
__status__ = "Development"
__date__ = "March 13, 2012"

class Deformation(SQTensor):
    """
    Subclass of SQTensor that describes the deformation gradient tensor
    """

    def __new__(cls, deformation_gradient, dfm=None):
        obj = SQTensor(deformation_gradient).view(cls)
        return obj

    def __array_finalize__(self, obj):
        if obj is None:
            return

    def __repr__(self):
        return "Deformation({})".format(self.__str__())

    def check_independent(self):
        """
        a check to determine whether the deformation matrix represents an
        independent deformation, raises a ValueError if not.  If so, returns 
        the indices of the deformation gradient entry representing the 
        independent component

        Args: tol
        """
        indices = zip(*np.asarray(self - np.eye(3)).nonzero())
        if len(indices) != 1:
            raise ValueError("One and only one independent deformation"\
                             "must be applied.")
        return indices[0]

    @property
    def euler_lagrange_strain(self):
        """
        calculates the euler-lagrange strain from
        the deformation gradient
        """
        return Strain.from_deformation(self)

    def apply_to_structure(self,structure):
        """
        Apply the deformation gradient to a structure.
        
        Args:
            structure (Structure object): the structure object to
                be modified by the deformation
        """
        def_struct = structure.copy()
        def_struct.modify_lattice(Lattice(np.dot(def_struct._lattice.matrix,
                                                 self)))
        return def_struct

    @classmethod
    def from_index_amount(cls,matrixpos, amt):
        """
        Factory method for constructing a Deformation object
        from a matrix position and amount

        Args:
            matrixpos (tuple): tuple corresponding the matrix position to
                have a perturbation added
            amt (float): amount to add to the identity matrix at position 
                matrixpos
        """
        F = np.identity(3)
        F[matrixpos] += amt
        return cls(F)

class DeformedStructureSet(object):
    """
    class that generates a set of deformed structures that
    can be used to fit the elastic tensor of a material
    """

    def __init__(self,rlxd_str, nd=0.01, ns=0.08, 
                 num_norm=4, num_shear=4, symmetry=False):
        """
        constructs the deformed geometries of a structure.  Generates
        m + n deformed structures according to the supplied parameters.

        Args:
            rlxd_str (structure): structure to undergo deformation, if 
                fitting elastic tensor is desired, should be a geometry 
                optimized structure
            nd (float): maximum perturbation applied to normal deformation
            ns (float): maximum perturbation applied to shear deformation
            m (int): number of deformation structures to generate for 
                normal deformation
            n (int): number of deformation structures to generate for 
                shear deformation
        """

        if num_norm%2 != 0:
            raise ValueError("Number of normal deformations (num_norm)"\
                             " must be even.")
        if num_shear%2 != 0:
            raise ValueError("Number of shear deformations (num_shear)"\
                             " must be even.")
        
        norm_deformations = np.linspace(-nd, nd, num=num_norm+1)
        norm_deformations = norm_deformations[norm_deformations.nonzero()]
        shear_deformations = np.linspace(-ns, ns, num=num_shear+1)
        shear_deformations = shear_deformations[shear_deformations.nonzero()]

        self.undeformed_structure = rlxd_str
        self.deformations = []
        self.def_structs = []
        if symmetry:
            raise NotImplementedError("Symmetry reduction of deformed "\
                                      "structure set not yet implemented")
        else:
            self.symmetry = None
            # Determine normal deformation gradients
            # Apply normal deformations
            for ind in [(0,0),(1,1),(2,2)]:
                for amount in norm_deformations:
                    defo = Deformation.from_index_amount(ind,amount)
                    self.deformations.append(defo)
                    self.def_structs.append(defo.apply_to_structure(rlxd_str))

            # Apply shear deformations 
            for ind in [(0,1),(0,2),(1,2)]:
                for amount in shear_deformations:
                    defo = Deformation.from_index_amount(ind,amount)
                    self.deformations.append(defo)
                    self.def_structs.append(defo.apply_to_structure(rlxd_str))

    def as_strain_dict(self):
        """
        Returns dictionary of deformed structures indexed by independent
        strain objects in accordance with legacy behavior of phonons
        package
        """
        strains = [IndependentStrain(defo) for defo in self.deformations]
        return dict(zip(strains,self.def_structs))



class Strain(SQTensor):
    """
    Subclass of SQTensor that describes the strain tensor
    """
        
    def __new__(cls, strain_matrix, dfm=None):
        obj = SQTensor(strain_matrix).view(cls)
        obj._dfm = dfm
        if dfm == None:
            warnings.warn("Constructing a strain object without a deformation "\
                          "matrix makes many methods unusable.  Use "\
                          "Strain.from_deformation to construct a Strain object"\
                          " from a deformation gradient.")
        return obj

    def __array_finalize__(self, obj):
        if obj is None:
            return
        self._dfm = getattr(obj, "_dfm", None)

    def __repr__(self):
        return "Strain({})".format(self.__str__())

    @classmethod
    def from_deformation(cls, deformation):
        """
        constructor that returns a Strain object from a deformation
        gradient

        Args:
            deformation (3x3 array-like):
        """
        dfm = Deformation(deformation)
        return cls(0.5*(dfm.T*dfm - np.eye(3)), dfm)

    @property
    def deformation_matrix(self):
        """
        returns the deformation matrix
        """
        return self._dfm
    
    @property
    def independent_deformation(self):
        """
        determines whether the deformation matrix represents an
        independent deformation, raises a value error if not.
        Returns the index of the deformation gradient corresponding
        to the independent deformation

        Args: tol
        """
        if self._dfm == None:
            raise ValueError("No deformation matrix supplied "\
                             "for this strain tensor.") 
        return self._dfm.check_independent()

    @property
    def voigt(self):
        """
        translates a strain tensor into a voigt notation vector
        """
        return [self[0,0],self[1,1],self[2,2],
                2.*self[1,2],2.*self[0,2],2.*self[0,1]]

class IndependentStrain(Strain):
    """
    Class for independent strains intended for use with old Materials Project
    elasticity workflow.  Note that the default constructor constructs from 
    a deformation matrix, rather than an array representing the strain, to 
    emulate the legacy behavior.
    """
    def __new__(cls, deformation_matrix):
        obj = Strain.from_deformation(deformation_matrix).view(cls)
        (obj._i,obj._j) = obj.independent_deformation
        return obj
    
    def __array_finalize__(self, obj):
        if obj is None:
            return
        self._dfm = getattr(obj, "_dfm", None)
        self._i = getattr(obj, "_i", None)
        self._j = getattr(obj, "_j", None)

    @property
    def i(self):
        return self._i

    @property
    def j(self):
        return self._j


if __name__ == "__main__":
    from pymatgen.matproj.rest import MPRester
    mpr = MPRester()
    d = Deformation(np.random.randn(3,3))
    d2 = Deformation.from_index_amount((1,1),0.1)
    Cu_struct = mpr.get_structures('Cu')[0]
    #d.apply_to_structure(Cu_struct)
    dss = DeformedStructureSet(Cu_struct)
    dss.as_strain_dict()
    mat = np.eye(3)
    mat[0,1] = 0.001

#    print mat

    my_strain = IndependentStrain(mat)
    #my_strain.check_F()


#    print my_strain._strain
    
    
    
#    print type(mat)

#    print my_strain.deformation_matrix
#    print my_strain.strain

#    my_strain2 = IndependentStrain(mat)
#    print my_strain2.__dict__.keys()
#    print my_strain2.__hash__()

#    print my_strain2._j
#    print my_strain2.check_F()
#    my_strain2.checkF
#    print my_strain.__dict__.keys()
#    print my_strain.deformation_matrix
#    print my_strain.strain
#    my_strain.index
#    my_scaled_strain = my_strain.get_scaled(1.05)
#    print my_scaled_strain.deformation_matrix
#    print my_scaled_strain.strain
#    print my_strain == my_scaled_strain
#    mat2 = np.eye(3)
#    mat2[0,0] = 1.01
#    my_strain2 = Strain(mat)
#    print my_strain == my_strain2


