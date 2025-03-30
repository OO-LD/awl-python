awl_context = {
    "@context": [
        {
            "awl": "https://w3id.org/awl/schema/",
            "ex": "https://example.org/",
            "@base": "https://w3id.org/awl/schema/",
            "_type": "@type",
            "id": "@id",
            "body": "awl:HasPart",
            "Name": {
                "@id": "awl:Variable",
                "@context": {"@base": "https://example.org/"},
            },
            "targets": "awl:HasTarget",
            "value": {"@id": "awl:HasValue", "@context": {"value": "@value"}},
            "If": {"@id": "awl:If", "@context": {"body": "awl:IfTrue"}},
            "orelse": "awl:IfFalse",
            "test": "awl:HasCondition",
            "comparators": "awl:HasRightHandComparator",
            "ops": "awl:HasOperator",
            "left": "awl:HasLeftHandComparator",
            "func": {
                "@id": "awl:HasFunctionCall",
                "@context": {
                    "@base": "https://example.org/",
                    "Name": "awl:Function",
                    "value": "awl:HasValue",
                },
            },
            "FunctionDef": {
                "@id": "awl:FunctionDef",
                "@context": {"@base": "https://example.org/", "name": "@id"},
            },
            "args": {
                "@id": "awl:HasArgumentList",
                "@context": {
                    "args": {
                        "@id": "awl:HasPart",
                        "@context": {
                            "_type:": None,
                            # "arg": "awl:HasKey",
                            "value": "awl:HasValue",
                            "annotation": "awl:HasType",
                        },
                    }
                },
            },
            "keywords": {
                "@id": "awl:HasKeywordArgument",
                "@context": {
                    "value": "awl:HasValue",
                    "annotation": "awl:HasAnnotation",
                },
            },
            "arg": "awl:HasKey",
            "returns": "awl:HasReturnType",
        }
    ]
}
