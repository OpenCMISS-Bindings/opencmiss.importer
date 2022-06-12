import os.path

import numpy as np
import trimesh

from opencmiss.zinc.context import Context
from opencmiss.zinc.element import Element, Elementbasis
from opencmiss.zinc.field import Field
from opencmiss.zinc.status import OK as ZINC_OK

from opencmiss.importer.base import valid
from opencmiss.importer.errors import OpenCMISSImportInvalidInputs, OpenCMISSImportUnknownParameter
from opencmiss.utils.zinc.field import findOrCreateFieldCoordinates
from opencmiss.utils.zinc.finiteelement import createTriangleElements, createNodes
from opencmiss.utils.zinc.general import ChangeManager


def import_data_into_region(region, inputs):
    if not valid(inputs, parameters("input")):
        raise OpenCMISSImportInvalidInputs(f"Invalid input given to importer: {identifier()}")

    input_file = inputs

    mesh = trimesh.load(input_file)

    field_module = region.getFieldmodule()
    with ChangeManager(field_module):
        coordinates = findOrCreateFieldCoordinates(field_module)
        node_set = field_module.findNodesetByFieldDomainType(Field.DOMAIN_TYPE_NODES)

        if isinstance(mesh, trimesh.Trimesh):
            createNodes(coordinates, mesh.vertices.tolist(), node_set=node_set)
            mesh2d = field_module.findMeshByDimension(2)
            # Trimesh triangles are zero-based, Zinc is 1-based
            triangles = mesh.faces + 1
            createTriangleElements(mesh2d, coordinates, triangles.tolist())
        else:
            stacked = [trimesh.util.stack_lines(e.discrete(mesh.vertices))
                       for e in mesh.entities]
            lines = trimesh.util.vstack_empty(stacked)
            # stack zeros for 2D lines
            is_2d_line = False
            if trimesh.util.is_shape(mesh.vertices, (-1, 2)):
                is_2d_line = True
                lines = lines.reshape((-1, 2))
                lines = np.column_stack((lines, np.zeros(len(lines))))

            lines_as_list = lines.tolist()

            pp = PointPare()
            pp.add_points(lines_as_list)
            pp.pare_points()

            createNodes(coordinates, pp.get_pared_points(), node_set=node_set)

            zinc_mesh = field_module.findMeshByDimension(1)
            linear_basis = field_module.createElementbasis(1, Elementbasis.FUNCTION_TYPE_LINEAR_LAGRANGE)
            element_template = zinc_mesh.createElementtemplate()
            element_template.setElementShapeType(Element.SHAPE_TYPE_LINE)
            element_template.setNumberOfNodes(2)
            eft = zinc_mesh.createElementfieldtemplate(linear_basis)
            element_template.defineField(coordinates, -1, eft)
            p_dict = {}
            for index, point in enumerate(lines_as_list):
                p_dict[hash(tuple(point))] = index

            with ChangeManager(field_module):
                line_count = 0
                for index, s in enumerate(stacked):
                    new_line = []
                    for p in s:
                        p_as_list = p.tolist()
                        if is_2d_line:
                            p_as_list.append(0.0)

                        index = p_dict[hash(tuple(p_as_list))]
                        # Node indexing is zero-based, Zinc is one-based
                        new_line.append(pp.get_pared_index(index) + 1)

                    line_index = 0
                    while line_index < len(new_line):
                        element = zinc_mesh.createElement(-1, element_template)
                        element.setNodesByIdentifier(eft, [new_line[line_index], new_line[line_index + 1]])
                        line_index += 2

                    line_count += 1


def import_data(inputs, output_directory):
    context = Context(identifier())
    region = context.getDefaultRegion()

    import_data_into_region(region, inputs)

    # Inputs has already been validated by this point so it is safe to use.
    filename_parts = os.path.splitext(os.path.basename(inputs))
    output_exf = os.path.join(output_directory, filename_parts[0] + ".exf")
    result = region.writeFile(output_exf)

    output = None
    if result == ZINC_OK:
        output = output_exf

    return output


# def identifier():
#     return "Trimesh"


# def parameters(parameter_name=None):
#     importer_parameters = {
#         "version": "0.1.0",
#         "id": identifier(),
#         "title": "Trimesh compatible meshes",
#         "description":
#             "Trimesh a library for loading and using triangular meshes.",
#         "input": {
#             "mimetype": "application/octet-stream",
#         },
#         "output": {
#             "mimetype": "text/x.vnd.abi.exf+plain",
#         }
#     }
#
#     if parameter_name is not None:
#         if parameter_name in importer_parameters:
#             return importer_parameters[parameter_name]
#         else:
#             raise OpenCMISSImportUnknownParameter(f"Importer '{identifier()}' does not have parameter: {parameter_name}")
#
#     return importer_parameters


class PointPare(object):

    def __init__(self):
        self._pared_points = []
        self._points = []
        self._point_map = {}
        self.clear_points()

    def clear_points(self):
        self._points = []
        self._point_map = {}

    def add_point(self, point):
        self._points.append(point)

    def add_points(self, points):
        self._points.extend(points)

    def pare_points(self):
        self._pared_points = []
        tmp = {}
        for index, pt in enumerate(self._points):
            dim = 0
            c_prev = []
            new_point = False
            while dim < len(pt):
                c = str(pt[dim])
                if dim == 0 and c not in tmp:
                    tmp[c] = {}
                elif dim == 1 and c not in tmp[c_prev[0]]:
                    tmp[c_prev[0]][c] = {}
                elif dim == 2 and c not in tmp[c_prev[0]][c_prev[1]]:
                    tmp[c_prev[0]][c_prev[1]] = {}
                    new_point = True

                c_prev.append(c)
                dim += 1

            if new_point:
                pared_index = len(self._pared_points)
                tmp[c_prev[0]][c_prev[1]][c_prev[2]] = pared_index
                self._pared_points.append(pt)
            else:
                pared_index = tmp[c_prev[0]][c_prev[1]][c_prev[2]]

            self._point_map[index] = pared_index

    def get_pared_index(self, point_index):
        """
        Return the pared node index for the original 
        node position.
        """
        return self._point_map[point_index]

    def get_pared_points(self):
        return self._pared_points
