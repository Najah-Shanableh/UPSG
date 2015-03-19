import tables
import uuid
import numpy as np
from utils import np_nd_to_sa, is_sa, np_type, np_sa_to_dict, dict_to_np_sa
from utils import sql_to_np, np_to_sql

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
    written and at least once when the UObject is being read. In order to 
    choose an interface, first create a UObject instance, and then invoke one
    of its methods prefixed with "to_" to read or "from_" to write.  For 
    example, to_postgres or from_dataframe. 

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
            return

        raise UObjectException('Invalid phase provided')

    def __del__(self):
        self.__file.close()

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

    def write_to_read_phase(self):
        """Converts a finalized UObject in its write phase into a UObject
        in its read phase.

        Use this function to pass the Python representation of a UObject
        between pipeline stages rather than just using the .upsg file.

        """
        if self.__phase == UObjectPhase.Read:
            return

        if not self.__finalized:
            raise UObjectException('UObject is not finalized')

        self.__file = tables.open_file(self.__file_name)
        self.__phase = UObjectPhase.Read
        self.__finalized = False

    def __convert_to(self, target_format, **kwargs):
        #TODO write this nicer than if statements
        #TODO include sql internal format
        storage_method = self.__file.get_node_attr('/upsg_inf', 'storage_method')
        hfile = self.__file
        if storage_method == 'np':
            A = hfile.root.np.table.read()
            if target_format == 'np':
                return A
            if target_format == 'dict':
                return np_sa_to_dict(A)
            if target_format == 'sql':
                raise NotImplementedError('Unsupported conversion')
                import sqlalchemy
                db_url = kwargs['db_url']
                con_params = kwargs['con_params']
                engine = sqlalchemy.create_engine(db_url)
                conn = engine.connect(**con_params)
                tbl_name = '_UPSG_' + str(uuid.uuid4()) 
                np_to_sql(A, tbl_name, conn)
                return tbl_name
            raise NotImplementedError('Unsupported conversion')
        if storage_method == 'sql':
            raise NotImplementedError('Unsupported internal format')
            db_url = hfile.root.sql.attrs.db_url
            con_params = np_sa_to_dict(hfile.root.sql.con_params.read())   
            tbl_name = hfile.root.sql.attrs.table
            if target_format == 'sql':
                return (db_url, con_params, tbl_name)
            import sqlalchemy
            engine = sqlalchemy.create_engine(db_url)
            conn = engine.connect(**con_params)
            md = sqlalchemy.MetaData()
            md.reflect(conn)
            tbl = md[tbl_name]
            result = sql_to_np(tbl, conn)
            if target_format == 'np':
                return result
            if target_format == 'dict':
                return np_sa_to_dict(result)
            raise NotImplementedError('Unsupported conversion')
        raise NotImplementedError('Unsupported internal format')

    def __to(self, converter):
        """Does generic book-keeping when a "to_" function is invoked.

        Every public-facing "to_" function should invoke this function. 

        Parameters
        ----------
        converter:  -> ?
            A function that produces the return value of the to_ 
            function. 

        Returns
        -------
        The return value of converter

        """

        if self.__phase != UObjectPhase.Read:
            raise UObjectException('UObject is not in the read phase')

        to_return = converter()
        self.__finalized = True 
        return to_return

    def to_np(self):
        """Makes the universal object available in a numpy array.

        Returns
        -------
        A numpy array encoding the data in this UObject

        """

        return self.__to(lambda: self.__convert_to('np'))

    def to_csv(self, file_name):
        """Makes the universal object available in a csv.

        Returns
        -------
        The path of the csv file

        """
        def converter():
            table = self.__convert_to('np')
            header = ",".join(map(
                lambda field_name: '"{}"'.format(field_name),
                table.dtype.names))
            np.savetxt(file_name, table, delimiter = ',', header = header,
                fmt = "%s")
            return file_name

        return self.__to(converter)
        
    
    def to_sql(self, db_url, con_params): 
        """Makes the universal object available in SQL.

        Returns 
        -------
        A tuple (db_url, con_params, query)

        """
        return self.__to(lambda: self.__convert_to('sql', db_url, con_params))    
    
    def to_dict(self):
        """Makes the universal object available in a dictionary.

        Returns 
        -------
        A dictionary containing a representation of the
        object.

        This is probably the choice to use when a universal object encodes
        parameters for a model.
        
        """

        return self.__to(lambda: self.__convert_to('dict'))

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
        filename: str
            The name of the csv file.

        """
        #TODO this is going to need to take more parameters

        def converter(hfile):
            
            data = np.genfromtxt(filename, dtype=None, delimiter=",", names=True)
            np_group = hfile.create_group('/', 'np')
            hfile.create_table(np_group, 'table', obj=data)
            return 'np'

        self.__from(converter)

    def from_np(self, A):
        """Writes the contents of a numpy array to a UObject and prepares the
        .upsg file.

        Parameters
        ----------
        A: numpy.array

        """

        def converter(hfile):
            if is_sa(A):
                to_write = A
            else:
                to_write = np_nd_to_sa(A)
            np_group = hfile.create_group('/', 'np')
            hfile.create_table(np_group, 'table', obj=to_write)
            return 'np'

        self.__from(converter)

    def from_sql(self, db_url, con_params, query):
        """Writes the results of a query to the universal object and prepares
        the .upsg file.

        Parameters
        ----------
        db_url : str
            The url of the database. Should conform to the format of 
            SQLAlchemy database URLS
            (http://docs.sqlalchemy.org/en/rel_0_9/core/engines.html#database-urls)
        con_params : dict of str to ?
            A dictionary of the keyword arguments to be passed to the connect
            method of some library implementing the Python Database API
            Specification 2.0
            (https://www.python.org/dev/peps/pep-0249/#connect)
        query : str
            query from which to derive the table which this UObject
            represents. Should be an SQL "SELECT" statement.

        """
        raise NotImplementedError()
        #todo make table from query
        def converter(hfile):
            sql_group = hfile.create_group('/', 'sql')
            hfile.create_table(sql_group, 'con_params', 
                dict_to_np_sa(con_params))
            hfile.set_node_attr(sql_group, 'db_url', db_url)
            # Make the table here...
            hfile.set_node_attr(sql_group, 'table', tbl_name)
            return 'sql'
        
        self.__from(converter)

    def from_dict(self, d):
        """Writes contents dictionary to the universal object
        and prepares the .upsg file.

        This is probably the choice to use when a universal object encodes
        parameters for a model.
        """
        
        def converter(hfile):
            np_group = hfile.create_group('/', 'np')
            hfile.create_table(np_group, 'table', obj=dict_to_np_sa(d))
            return 'np'
        
        self.__from(converter)
