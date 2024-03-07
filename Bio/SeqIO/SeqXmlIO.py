# Copyright 2010 by Thomas Schmitt.
#
# This file is part of the Biopython distribution and governed by your
# choice of the "Biopython License Agreement" or the "BSD 3-Clause License".
# Please see the LICENSE file that should have been included as part of this
# package.
"""Bio.SeqIO support for the "seqxml" file format, SeqXML.

This module is for reading and writing SeqXML format files as
SeqRecord objects, and is expected to be used via the Bio.SeqIO API.

SeqXML is a lightweight XML format which is supposed be an alternative for
FASTA files. For more Information see http://www.seqXML.org and Schmitt et al
(2011), https://doi.org/10.1093/bib/bbr025
"""

from xml import sax
from xml.sax import handler
from xml.sax.saxutils import XMLGenerator
from xml.sax.xmlreader import AttributesImpl

from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from .Interfaces import SequenceIterator
from .Interfaces import SequenceWriter


class ContentHandler(handler.ContentHandler):
    """Handles XML events generated by the parser (PRIVATE)."""

    def __init__(self):
        """Create a handler to handle XML events."""
        super().__init__()
        self.source = None
        self.sourceVersion = None
        self.seqXMLversion = None
        self.ncbiTaxID = None
        self.speciesName = None
        self.startElementNS = None
        self.data = None
        self.records = []

    def startDocument(self):
        """Set XML handlers when an XML declaration is found."""
        self.startElementNS = self.startSeqXMLElement

    def startSeqXMLElement(self, name, qname, attrs):
        """Handle start of a seqXML element."""
        if name != (None, "seqXML"):
            raise ValueError("Failed to find the start of seqXML element")
        if qname is not None:
            raise RuntimeError("Unexpected qname for seqXML element")
        schema = None
        for key, value in attrs.items():
            namespace, localname = key
            if namespace is None:
                if localname == "source":
                    self.source = value
                elif localname == "sourceVersion":
                    self.sourceVersion = value
                elif localname == "seqXMLversion":
                    self.seqXMLversion = value
                elif localname == "ncbiTaxID":
                    # check if it is an integer, but store as string
                    number = int(value)
                    self.ncbiTaxID = value
                elif localname == "speciesName":
                    self.speciesName = value
                else:
                    raise ValueError("Unexpected attribute for XML Schema")
            elif namespace == "http://www.w3.org/2001/XMLSchema-instance":
                if localname == "noNamespaceSchemaLocation":
                    schema = value
                else:
                    raise ValueError("Unexpected attribute for XML Schema in namespace")
            else:
                raise ValueError(
                    f"Unexpected namespace '{namespace}' for seqXML attribute"
                )
        if self.seqXMLversion is None:
            raise ValueError("Failed to find seqXMLversion")
        elif self.seqXMLversion not in ("0.1", "0.2", "0.3", "0.4"):
            raise ValueError("Unsupported seqXMLversion")
        url = f"http://www.seqxml.org/{self.seqXMLversion}/seqxml.xsd"
        if schema is not None and schema != url:
            raise ValueError(
                "XML Schema '%s' found not consistent with reported seqXML version %s"
                % (schema, self.seqXMLversion)
            )
        # speciesName and ncbiTaxID attributes on the root are only supported
        # in 0.4
        if self.speciesName and self.seqXMLversion != "0.4":
            raise ValueError(
                "Attribute 'speciesName' on root is only supported in version 0.4"
            )
        if self.ncbiTaxID and self.seqXMLversion != "0.4":
            raise ValueError(
                "Attribute 'ncbiTaxID' on root is only supported in version 0.4"
            )
        self.endElementNS = self.endSeqXMLElement
        self.startElementNS = self.startEntryElement

    def endSeqXMLElement(self, name, qname):
        """Handle end of the seqXML element."""
        namespace, localname = name
        if namespace is not None:
            raise RuntimeError(f"Unexpected namespace '{namespace}' for seqXML end")
        if qname is not None:
            raise RuntimeError(f"Unexpected qname '{qname}' for seqXML end")
        if localname != "seqXML":
            raise RuntimeError("Failed to find end of seqXML element")
        self.startElementNS = None
        self.endElementNS = None

    def startEntryElement(self, name, qname, attrs):
        """Set new entry with id and the optional entry source (PRIVATE)."""
        if name != (None, "entry"):
            raise ValueError("Expected to find the start of an entry element")
        if qname is not None:
            raise RuntimeError("Unexpected qname for entry element")
        record = SeqRecord(None, id=None)
        if self.speciesName is not None:
            record.annotations["organism"] = self.speciesName
        if self.ncbiTaxID is not None:
            record.annotations["ncbi_taxid"] = self.ncbiTaxID
        record.annotations["source"] = self.source
        for key, value in attrs.items():
            namespace, localname = key
            if namespace is None:
                if localname == "id":
                    record.id = value
                elif localname == "source" and (
                    self.seqXMLversion == "0.3" or self.seqXMLversion == "0.4"
                ):
                    record.annotations["source"] = value
                else:
                    raise ValueError(
                        f"Unexpected attribute {localname} in entry element"
                    )
            else:
                raise ValueError(
                    f"Unexpected namespace '{namespace}' for entry attribute"
                )
        if record.id is None:
            raise ValueError("Failed to find entry ID")
        self.records.append(record)
        if self.seqXMLversion == "0.1":
            self.startElementNS = self.startEntryFieldElementVersion01
        else:
            self.startElementNS = self.startEntryFieldElement
        self.endElementNS = self.endEntryElement

    def endEntryElement(self, name, qname):
        """Handle end of an entry element."""
        if name != (None, "entry"):
            raise ValueError("Expected to find the end of an entry element")
        if qname is not None:
            raise RuntimeError("Unexpected qname for entry element")
        if self.records[-1].seq is None:
            raise ValueError("Failed to find a sequence for entry element")
        self.startElementNS = self.startEntryElement
        self.endElementNS = self.endSeqXMLElement

    def startEntryFieldElementVersion01(self, name, qname, attrs):
        """Receive a field of an entry element and forward it for version 0.1."""
        namespace, localname = name
        if namespace is not None:
            raise ValueError(
                f"Unexpected namespace '{namespace}' for {localname} element"
            )
        if qname is not None:
            raise RuntimeError(f"Unexpected qname '{qname}' for {localname} element")
        if localname == "species":
            return self.startSpeciesElement(attrs)
        if localname == "description":
            return self.startDescriptionElement(attrs)
        if localname in ("dnaSeq", "rnaSeq", "aaSeq"):
            return self.startSequenceElement(attrs)
        if localname == "alternativeID":
            return self.startDBRefElement(attrs)
        if localname == "property":
            return self.startPropertyElement(attrs)
        raise ValueError(f"Unexpected field {localname} in entry")

    def startEntryFieldElement(self, name, qname, attrs):
        """Receive a field of an entry element and forward it for versions >=0.2."""
        namespace, localname = name
        if namespace is not None:
            raise ValueError(
                f"Unexpected namespace '{namespace}' for {localname} element"
            )
        if qname is not None:
            raise RuntimeError(f"Unexpected qname '{qname}' for {localname} element")
        if localname == "species":
            return self.startSpeciesElement(attrs)
        if localname == "description":
            return self.startDescriptionElement(attrs)
        if localname in ("DNAseq", "RNAseq", "AAseq"):
            return self.startSequenceElement(attrs)
        if localname == "DBRef":
            return self.startDBRefElement(attrs)
        if localname == "property":
            return self.startPropertyElement(attrs)
        raise ValueError(f"Unexpected field {localname} in entry")

    def startSpeciesElement(self, attrs):
        """Parse the species information."""
        name = None
        ncbiTaxID = None
        for key, value in attrs.items():
            namespace, localname = key
            if namespace is None:
                if localname == "name":
                    name = value
                elif localname == "ncbiTaxID":
                    # check if it is an integer, but store as string
                    number = int(value)
                    ncbiTaxID = value
                else:
                    raise ValueError(
                        f"Unexpected attribute '{key}' found in species tag"
                    )
            else:
                raise ValueError(
                    f"Unexpected namespace '{namespace}' for species attribute"
                )
        # The attributes "name" and "ncbiTaxID" are required:
        if name is None:
            raise ValueError("Failed to find species name")
        if ncbiTaxID is None:
            raise ValueError("Failed to find ncbiTaxId")
        record = self.records[-1]
        # The keywords for the species annotation are taken from SwissIO
        record.annotations["organism"] = name
        # TODO - Should have been a list to match SwissProt parser:
        record.annotations["ncbi_taxid"] = ncbiTaxID
        self.endElementNS = self.endSpeciesElement

    def endSpeciesElement(self, name, qname):
        """Handle end of a species element."""
        namespace, localname = name
        if namespace is not None:
            raise RuntimeError(f"Unexpected namespace '{namespace}' for species end")
        if qname is not None:
            raise RuntimeError(f"Unexpected qname '{qname}' for species end")
        if localname != "species":
            raise RuntimeError("Failed to find end of species element")
        self.endElementNS = self.endEntryElement

    def startDescriptionElement(self, attrs):
        """Parse the description."""
        if attrs:
            raise ValueError("Unexpected attributes found in description element")
        if self.data is not None:
            raise RuntimeError(f"Unexpected data found: '{self.data}'")
        self.data = ""
        self.endElementNS = self.endDescriptionElement

    def endDescriptionElement(self, name, qname):
        """Handle the end of a description element."""
        namespace, localname = name
        if namespace is not None:
            raise RuntimeError(
                f"Unexpected namespace '{namespace}' for description end"
            )
        if qname is not None:
            raise RuntimeError(f"Unexpected qname '{qname}' for description end")
        if localname != "description":
            raise RuntimeError("Failed to find end of description element")
        record = self.records[-1]
        description = self.data
        if description:  # ignore if empty string
            record.description = description
        self.data = None
        self.endElementNS = self.endEntryElement

    def startSequenceElement(self, attrs):
        """Parse DNA, RNA, or protein sequence."""
        if attrs:
            raise ValueError("Unexpected attributes found in sequence element")
        if self.data is not None:
            raise RuntimeError(f"Unexpected data found: '{self.data}'")
        self.data = ""
        self.endElementNS = self.endSequenceElement

    def endSequenceElement(self, name, qname):
        """Handle the end of a sequence element."""
        namespace, localname = name
        if namespace is not None:
            raise RuntimeError(f"Unexpected namespace '{namespace}' for sequence end")
        if qname is not None:
            raise RuntimeError(f"Unexpected qname '{qname}' for sequence end")
        record = self.records[-1]
        if (localname == "DNAseq" and self.seqXMLversion != "0.1") or (
            localname == "dnaSeq" and self.seqXMLversion == "0.1"
        ):
            record.annotations["molecule_type"] = "DNA"
        elif (localname == "RNAseq" and self.seqXMLversion != "0.1") or (
            localname == "rnaSeq" and self.seqXMLversion == "0.1"
        ):
            record.annotations["molecule_type"] = "RNA"
        elif (localname == "AAseq" and self.seqXMLversion >= "0.1") or (
            localname == "aaSeq" and self.seqXMLversion == "0.1"
        ):
            record.annotations["molecule_type"] = "protein"
        else:
            raise RuntimeError(
                f"Failed to find end of sequence (localname = {localname})"
            )
        record.seq = Seq(self.data)
        self.data = None
        self.endElementNS = self.endEntryElement

    def startDBRefElement(self, attrs):
        """Parse a database cross reference."""
        TYPE = None
        source = None
        ID = None
        for key, value in attrs.items():
            namespace, localname = key
            if namespace is None:
                if localname == "type":
                    TYPE = value
                elif localname == "source":
                    source = value
                elif localname == "id":
                    ID = value
                else:
                    raise ValueError(
                        f"Unexpected attribute '{key}' found for DBRef element"
                    )
            else:
                raise ValueError(
                    f"Unexpected namespace '{namespace}' for DBRef attribute"
                )
        # The attributes "source" and "id" are required, and "type" in versions
        # 0.2-0.3:
        if source is None:
            raise ValueError("Failed to find source for DBRef element")
        if ID is None:
            raise ValueError("Failed to find id for DBRef element")
        if TYPE is None and (
            self.seqXMLversion == "0.2" or self.seqXMLversion == "0.3"
        ):
            raise ValueError("Failed to find type for DBRef element")
        if self.data is not None:
            raise RuntimeError(f"Unexpected data found: '{self.data}'")
        self.data = ""
        record = self.records[-1]
        dbxref = f"{source}:{ID}"
        if dbxref not in record.dbxrefs:
            record.dbxrefs.append(dbxref)
        self.endElementNS = self.endDBRefElement

    def endDBRefElement(self, name, qname):
        """Handle the end of a DBRef element."""
        namespace, localname = name
        if namespace is not None:
            raise RuntimeError(f"Unexpected namespace '{namespace}' for DBRef element")
        if qname is not None:
            raise RuntimeError(f"Unexpected qname '{qname}' for DBRef element")
        if (localname != "DBRef" and self.seqXMLversion != "0.1") or (
            localname != "alternativeID" and self.seqXMLversion == "0.1"
        ):
            raise RuntimeError(f"Unexpected localname '{localname}' for DBRef element")
        if self.data:
            raise RuntimeError(
                f"Unexpected data received for DBRef element: '{self.data}'"
            )
        self.data = None
        self.endElementNS = self.endEntryElement

    def startPropertyElement(self, attrs):
        """Handle the start of a property element."""
        property_name = None
        property_value = None
        for key, value in attrs.items():
            namespace, localname = key
            if namespace is None:
                if localname == "name":
                    property_name = value
                elif localname == "value":
                    property_value = value
                else:
                    raise ValueError(
                        "Unexpected attribute '%s' found for property element", key
                    )
            else:
                raise ValueError(
                    f"Unexpected namespace '{namespace}' for property attribute"
                )
        # The attribute "name" is required:
        if property_name is None:
            raise ValueError("Failed to find name for property element")
        record = self.records[-1]
        if property_name == "molecule_type":
            # At this point, record.annotations["molecule_type"] is either
            # "DNA", "RNA", or "protein"; property_value may be a more detailed
            # description such as "mRNA" or "genomic DNA".
            assert record.annotations[property_name] in property_value
            record.annotations[property_name] = property_value
        else:
            if property_name not in record.annotations:
                record.annotations[property_name] = []
            record.annotations[property_name].append(property_value)
        self.endElementNS = self.endPropertyElement

    def endPropertyElement(self, name, qname):
        """Handle the end of a property element."""
        namespace, localname = name
        if namespace is not None:
            raise RuntimeError(
                f"Unexpected namespace '{namespace}' for property element"
            )
        if qname is not None:
            raise RuntimeError(f"Unexpected qname '{qname}' for property element")
        if localname != "property":
            raise RuntimeError(
                f"Unexpected localname '{localname}' for property element"
            )
        self.endElementNS = self.endEntryElement

    def characters(self, data):
        """Handle character data."""
        if self.data is not None:
            self.data += data


class SeqXmlIterator(SequenceIterator):
    """Parser for seqXML files.

    Parses seqXML files and creates SeqRecords.
    Assumes valid seqXML please validate beforehand.
    It is assumed that all information for one record can be found within a
    record element or above. Two types of methods are called when the start
    tag of an element is reached. To receive only the attributes of an
    element before its end tag is reached implement _attr_TAGNAME.
    To get an element and its children as a DOM tree implement _elem_TAGNAME.
    Everything that is part of the DOM tree will not trigger any further
    method calls.
    """

    BLOCK = 1024

    def __init__(self, stream_or_path, namespace=None):
        """Create the object and initialize the XML parser."""
        # Make sure we got a binary handle. If we got a text handle, then
        # the parser will still run but unicode characters will be garbled
        # if the text handle was opened with a different encoding than the
        # one specified in the XML file. With a binary handle, the correct
        # encoding is picked up by the parser from the XML file.
        self.parser = sax.make_parser()
        content_handler = ContentHandler()
        self.parser.setContentHandler(content_handler)
        self.parser.setFeature(handler.feature_namespaces, True)
        super().__init__(stream_or_path, mode="b", fmt="SeqXML")

    def parse(self, handle):
        """Start parsing the file, and return a SeqRecord generator."""
        parser = self.parser
        content_handler = parser.getContentHandler()
        BLOCK = self.BLOCK
        while True:
            # Read in another block of the file...
            text = handle.read(BLOCK)
            if not text:
                if content_handler.startElementNS is None:
                    raise ValueError("Empty file.")
                else:
                    raise ValueError("XML file contains no data.")
            parser.feed(text)
            seqXMLversion = content_handler.seqXMLversion
            if seqXMLversion is not None:
                break
        self.seqXMLversion = seqXMLversion
        self.source = content_handler.source
        self.sourceVersion = content_handler.sourceVersion
        self.ncbiTaxID = content_handler.ncbiTaxID
        self.speciesName = content_handler.speciesName
        records = self.iterate(handle)
        return records

    def iterate(self, handle):
        """Iterate over the records in the XML file."""
        parser = self.parser
        content_handler = parser.getContentHandler()
        records = content_handler.records
        BLOCK = self.BLOCK
        while True:
            if len(records) > 1:
                # Then at least the first record is finished
                record = records.pop(0)
                yield record
            # Read in another block of the file...
            text = handle.read(BLOCK)
            if not text:
                break
            parser.feed(text)
        # We have reached the end of the XML file;
        # send out the remaining records
        yield from records
        records.clear()
        parser.close()


class SeqXmlWriter(SequenceWriter):
    """Writes SeqRecords into seqXML file.

    SeqXML requires the SeqRecord annotations to specify the molecule_type;
    the molecule type is required to contain the term "DNA", "RNA", or
    "protein".
    """

    def __init__(
        self, target, source=None, source_version=None, species=None, ncbiTaxId=None
    ):
        """Create Object and start the xml generator.

        Arguments:
         - target - Output stream opened in binary mode, or a path to a file.
         - source - The source program/database of the file, for example
           UniProt.
         - source_version - The version or release number of the source
           program or database from which the data originated.
         - species - The scientific name of the species of origin of all
           entries in the file.
         - ncbiTaxId - The NCBI taxonomy identifier of the species of origin.

        """
        super().__init__(target, "wb")
        handle = self.handle
        self.xml_generator = XMLGenerator(handle, "utf-8")
        self.xml_generator.startDocument()
        self.source = source
        self.source_version = source_version
        self.species = species
        self.ncbiTaxId = ncbiTaxId

    def write_header(self):
        """Write root node with document metadata."""
        attrs = {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "http://www.seqxml.org/0.4/seqxml.xsd",
            "seqXMLversion": "0.4",
        }

        if self.source is not None:
            attrs["source"] = self.source
        if self.source_version is not None:
            attrs["sourceVersion"] = self.source_version
        if self.species is not None:
            if not isinstance(self.species, str):
                raise TypeError("species should be of type string")
            attrs["speciesName"] = self.species
        if self.ncbiTaxId is not None:
            if not isinstance(self.ncbiTaxId, (str, int)):
                raise TypeError("ncbiTaxID should be of type string or int")
            attrs["ncbiTaxID"] = self.ncbiTaxId

        self.xml_generator.startElement("seqXML", AttributesImpl(attrs))

    def write_record(self, record):
        """Write one record."""
        if not record.id or record.id == "<unknown id>":
            raise ValueError("SeqXML requires identifier")

        if not isinstance(record.id, str):
            raise TypeError("Identifier should be of type string")

        attrb = {"id": record.id}

        if (
            "source" in record.annotations
            and self.source != record.annotations["source"]
        ):
            if not isinstance(record.annotations["source"], str):
                raise TypeError("source should be of type string")
            attrb["source"] = record.annotations["source"]

        self.xml_generator.startElement("entry", AttributesImpl(attrb))
        self._write_species(record)
        self._write_description(record)
        self._write_seq(record)
        self._write_dbxrefs(record)
        self._write_properties(record)
        self.xml_generator.endElement("entry")

    def write_footer(self):
        """Close the root node and finish the XML document."""
        self.xml_generator.endElement("seqXML")
        self.xml_generator.endDocument()

    def _write_species(self, record):
        """Write the species if given (PRIVATE)."""
        local_ncbi_taxid = None
        if "ncbi_taxid" in record.annotations:
            local_ncbi_taxid = record.annotations["ncbi_taxid"]
            if isinstance(local_ncbi_taxid, list):
                # SwissProt parser uses a list (which could cope with chimeras)
                if len(local_ncbi_taxid) == 1:
                    local_ncbi_taxid = local_ncbi_taxid[0]
                elif len(local_ncbi_taxid) == 0:
                    local_ncbi_taxid = None
                else:
                    raise ValueError(
                        "Multiple entries for record.annotations['ncbi_taxid'], %r"
                        % local_ncbi_taxid
                    )
        if "organism" in record.annotations and local_ncbi_taxid:
            local_org = record.annotations["organism"]

            if not isinstance(local_org, str):
                raise TypeError("organism should be of type string")

            if not isinstance(local_ncbi_taxid, (str, int)):
                raise TypeError("ncbiTaxID should be of type string or int")

            # The local species definition is only written if it differs from the global species definition
            if local_org != self.species or local_ncbi_taxid != self.ncbiTaxId:
                attr = {"name": local_org, "ncbiTaxID": str(local_ncbi_taxid)}
                self.xml_generator.startElement("species", AttributesImpl(attr))
                self.xml_generator.endElement("species")

    def _write_description(self, record):
        """Write the description if given (PRIVATE)."""
        if record.description:
            if not isinstance(record.description, str):
                raise TypeError("Description should be of type string")

            description = record.description
            if description == "<unknown description>":
                description = ""

            if len(record.description) > 0:
                self.xml_generator.startElement("description", AttributesImpl({}))
                self.xml_generator.characters(description)
                self.xml_generator.endElement("description")

    def _write_seq(self, record):
        """Write the sequence (PRIVATE).

        Note that SeqXML requires the molecule type to contain the term
        "DNA", "RNA", or "protein".
        """
        seq = bytes(record.seq)

        if not len(seq) > 0:
            raise ValueError("The sequence length should be greater than 0")

        molecule_type = record.annotations.get("molecule_type")
        if molecule_type is None:
            raise ValueError("molecule_type is not defined")
        elif "DNA" in molecule_type:
            seqElem = "DNAseq"
        elif "RNA" in molecule_type:
            seqElem = "RNAseq"
        elif "protein" in molecule_type:
            seqElem = "AAseq"
        else:
            raise ValueError(f"unknown molecule_type '{molecule_type}'")

        self.xml_generator.startElement(seqElem, AttributesImpl({}))
        self.xml_generator.characters(seq)
        self.xml_generator.endElement(seqElem)

    def _write_dbxrefs(self, record):
        """Write all database cross references (PRIVATE)."""
        if record.dbxrefs is not None:
            for dbxref in record.dbxrefs:
                if not isinstance(dbxref, str):
                    raise TypeError("dbxrefs should be of type list of string")
                if dbxref.find(":") < 1:
                    raise ValueError(
                        "dbxrefs should be in the form ['source:id', 'source:id' ]"
                    )

                dbsource, dbid = dbxref.split(":", 1)

                attr = {"source": dbsource, "id": dbid}
                self.xml_generator.startElement("DBRef", AttributesImpl(attr))
                self.xml_generator.endElement("DBRef")

    def _write_properties(self, record):
        """Write all annotations that are key value pairs with values of a primitive type or list of primitive types (PRIVATE)."""
        for key, value in record.annotations.items():
            if key not in ("organism", "ncbi_taxid", "source"):
                if value is None:
                    attr = {"name": key}
                    self.xml_generator.startElement("property", AttributesImpl(attr))
                    self.xml_generator.endElement("property")

                elif isinstance(value, list):
                    for v in value:
                        if v is None:
                            attr = {"name": key}
                        else:
                            attr = {"name": key, "value": str(v)}
                        self.xml_generator.startElement(
                            "property", AttributesImpl(attr)
                        )
                        self.xml_generator.endElement("property")

                elif isinstance(value, (int, float, str)):
                    attr = {"name": key, "value": str(value)}
                    self.xml_generator.startElement("property", AttributesImpl(attr))
                    self.xml_generator.endElement("property")
