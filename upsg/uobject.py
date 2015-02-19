import tables
import uuid
import numpy as np

class UObjectException(Exception):
    """Exception related to UObjects"""
    pass

class UObjectPhase:
    """Enumeration of UObject phases

    UObjects are write-once. They must be written, then read.
    This enumeration specifies what is happening at present. 

    """
    Write, Read = range(2)
    All = (Write, Read)

class UObject:
    """A universal object signifying intermediary state in a pipeline.

    Conceptually, this object is a write-once table. It can be written
    and read using a number of interfaces. For example, it can be treated
    as a table in a PostgreSQL database or a Pandas dataframe residing in
    memory. The internal representation is up to UPSG. Regardless of 
    internal representation, each UObject will be represented by a
    .upsg file that resides on the local disk. This .upsg file will be used
    to communicate between different steps in the pipeline.

    The interface to use will be chosen once when the UObject is being
    written and once when the UObject is being read. In order to choose
    an interface, first create a UObject instance, and then invoke one of
    its methods prefixed with "to_" to read or "from_" to write. 
    For example, to_postgres or from_dataframe. 

    If an object is invoked in write mode, it must be finalized
    before it can be read by another phase in the pipeline using one of
    the "to_" methods.

    """
    
    def __init__(self, phase, file_name = None):
        """initializer

        Prepares a UObject to be further used in a program. After a UObject
        instance is created, then the interface can be chosen and it can be
        read or written to in the rest of the program. Each instance of 
        UObject must be either read-only or write-only. 

        Parameters
        ----------
        phase: A member of UObjectPhase specifying whether the U_object
            is being written or read. Should be either UObjectPhase.Write
            or UObjectPhase.Read, respectively.
        file_name: The name of the .upsg file representing this universal
            intermediary object. 

            If the file is being written, this argument is optional. If not 
            specified, an arbitrary, unique filename will be chosen. This
            filename can be found by invoking the get_file_name function.

            If the file is being read, this argument is mandatory. Failure
            to specify the argument will result in an exception.

        """
        self.__phase = phase
        self.__finalized = False
        self.__file_name = file_name

        if phase == UObjectPhase.Write:
            if self.__file_name is None:
                self.__file_name = str(uuid.uuid4()) + '.upsg'
            self.__file = tables.open_file(self.__file_name, mode = 'w')
            upsg_inf_grp = self.__file.create_group('/', 'upsg_inf')
            self.__file.set_node_attr(upsg_inf_grp, 'storage_method', 'INCOMPLETE')
            self.__file.flush()
            return
            
        if phase == UObjectPhase.Read:
            if self.__file_name is None:
                raise UObjectException('Specified read phase without providing file name')
            self.__file = tables.open_file(self.__file_name, mode = 'r')

        raise UObjectException('Invalid phase provided')

    def get_phase(self):
        """returns a member of UObjectPhase signifying whether the UObject
        is being read or written."""
        return self.__phase
    
    def get_file_name(self):
        """Returns the path of this UObject's .upsg file."""
        return self.__file_name

    def is_finalized(self):
        """

        If the UObject is being written, returns a boolean signifying
        whether or not one of the "from_" methods has been called yet.

        If the UObject is being read, returns a boolean specifying
        whether or not one of the "to_" methods has been called yet.

        """
        return self.__finalized

    def to_read_phase(self):
        """Converts a finalized UObject in its write phase into a UObject
        in its read phase.

        Use this function to pass the Python representation of a UObject
        between pipeline stages rather than just using the .upsg file.

        """
        if self.__phase != UObjectPhase.Write:
            raise UObjectException('UObject is not in write phase')
        if not self.__finalized:
            raise UObjectException('UObject is not finalized')

        self.__file = tables.open_file(self.__file_name)
        self.__phase = UObjectPhase.Read
        self.__finalized = False

    def __to(self, converter):
        """Does generic book-keeping when a "to_" function is invoked.

        Every public-facing "to_" function should invoke this function. 

        Parameters
        ----------
        converter:  (string, tables.File) -> ?
            A function that produces the return value of the to_ 
            function. The first parameter is the storage method. The
            second is pytables file in which the data is stored. 

        Returns
        -------
        The return value of converter

        """

        if self.__phase != UObjectPhase.Read:
            raise UObjectException('UObject is not in the read phase')
        if self.__finalized:
            raise UObjectException('UObject is already finalized')

        storage_method = self.__file.get_node_attr('/upsg_inf', 'storage_method')
        to_return = converter(storage_method, self.__file)
        self.__file.close()
        self.__finalized = True 
        return to_return

    def to_np(self):
        """Makes the universal object available in a numpy array.

        Returns
        -------
        A numpy array encoding the data in this UObject

        """
        def converter(storage_method, hfile):
            if storage_method == 'np':
                return hfile.root.np.table.read()
            raise UObjectException('Unsupported internal representation')

        return self.__to(converter)
    
    def to_postgresql(self): 
        """Makes the universal object available in postgres.

        Returns 
        -------
        A tuple (connection_string, table_name)

        """
        #TODO stub
        return ('', '')
    
    def to_dataframe(self):
        """Makes the universal object available in a Python dataframe.

        Returns 
        -------
        A Pandas dataframe containing a representation of the object.

        """
        #TODO stub
        return None
    
    def to_tuple_of_dicts(self):
        """Makes the universal object available in a tuple of dictionaries.

        Returns 
        -------
        A tuple of dictionaries containing a representation of the
        object.

        This is probably the choice to use when a universal object encodes
        parameters for a model.
        
        """
        #TODO stub
        return ()

    def __from(self, converter):
        """Does generic book-keeping when a "from_function is invoked.

        Every public-facing "from_" function should invoke this function.

        Parameters
        ----------
        converter: tables.File -> string
            A function that updates the passed file as specified
            by the from_ function. It should return the storage method
            being used

        """
        
        if self.__phase != UObjectPhase.Write:
            raise UObjectException('UObject is not in write phase')
        if self.__finalized:
            raise UObjectException('UObject is already finalized')

        storage_method = converter(self.__file)

        self.__file.set_node_attr('/upsg_inf', 'storage_method', storage_method)
        self.__file.flush()
        self.__file.close()
        self.__finalized = True

    def from_csv(self, filename):
        """Writes the contents of a CSV to the UOBject and prepares the .upsg
        file.

        Parameters
        ----------
        filename: string
            The name of the csv file.

        """
        #TODO this is going to need to take more parameters

        def converter(hfile):
            
            data = np.genfromtxt(filename, dtype=None, delimiter=",", names=True)
            np_group = hfile.create_group('/', 'np')
            hfile.create_table(np_group, 'table', obj=data)
            return 'np'

        self.__from(converter)

    def from_postgres(self, con_string, query):
        """Writes the results of a query to the universal object and prepares
        the .upsg file.

        """
        #TODO stub
        pass

    def from_dataframe(self, dataframe):
        """Writes contents of a Pandas dataframe to the universal object and 
        prepares the .upsg file.

        """
        #TODO stub
        pass

    def from_tuple_of_dicts(self, tuple_of_dicts):
        """Writes contents of a tuple of dictionaries to the universal object
        and prepares the .upsg file.

        This is probably the choice to use when a universal object encodes
        parameters for a model.
        """
        #todo stub
        pass